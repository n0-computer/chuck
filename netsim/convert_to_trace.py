#!/usr/bin/env python3
"""Convert netsim output to trace-server format."""

import sys
import json
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime
import uuid

def parse_events_from_logs(prefix, nodes_info):
    """Extract EVENT: lines from log files"""
    log_files = list(Path("logs").glob(f"{prefix}__*.txt"))
    node_name_to_idx = {node["name"]: node["idx"] for node in nodes_info}
    events = []

    for log_file in log_files:
        node_name = log_file.stem.replace(f"{prefix}__", "")
        src_idx = node_name_to_idx.get(node_name, 0)

        with open(log_file) as f:
            for line in f:
                if line.startswith('EVENT:'):
                    try:
                        event_data = json.loads(line[6:])
                        event_type = event_data.get('type')
                        timestamp_unix = event_data.get('timestamp')
                        timestamp = datetime.utcfromtimestamp(timestamp_unix).isoformat() + "Z"

                        # Map event types
                        if event_type in ['ConnectionAttempt', 'ConnectionEstablished', 'TransferStart', 'TransferComplete']:
                            events.append({
                                "type": {"User": {"label": event_type}},
                                "src_node": src_idx,
                                "dst_node": src_idx,
                                "id": None,
                                "start": timestamp,
                            })
                    except (json.JSONDecodeError, KeyError):
                        pass

    return events

def extract_node_id_from_log(log_file):
    with open(log_file) as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            match = re.search(r'(?:Node ID|Endpoint id):\s*([a-z0-9]{52})', line, re.IGNORECASE)
            if match:
                return match.group(1)
            if re.search(r'(?:endpoint id|node id):\s*$', line, re.IGNORECASE):
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if re.match(r'^[a-z0-9]{52,}$', next_line, re.IGNORECASE):
                        return next_line[:64] if len(next_line) > 64 else next_line
    return None

def extract_timestamp_from_log_line(line):
    """Extract timestamp from ANSI-formatted log line"""
    # Match patterns like: [2m2025-11-22T13:47:15.718924Z[0m
    match = re.search(r'\[2m(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\[0m', line)
    if match:
        return match.group(1)
    # Also try without ANSI codes
    match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)', line)
    if match:
        return match.group(1)
    return None

def convert_logs_to_jsonnd(prefix, output_path, nodes_info):
    log_files = list(Path("logs").glob(f"{prefix}__*.txt"))
    total_lines = 0

    # Create node name to idx mapping
    node_name_to_idx = {node["name"]: node["idx"] for node in nodes_info}

    with open(output_path, 'w') as outfile:
        for log_file in log_files:
            node_name = log_file.stem.replace(f"{prefix}__", "")
            node_id = extract_node_id_from_log(log_file)
            node_idx = node_name_to_idx.get(node_name)

            with open(log_file) as infile:
                for line in infile:
                    line = line.strip()
                    if not line or line.startswith('cmd:') or line.startswith('METRICS:') or line.startswith('PROGRESS:'):
                        continue

                    # Extract timestamp from log line
                    timestamp = extract_timestamp_from_log_line(line)
                    if not timestamp:
                        timestamp = datetime.utcnow().isoformat() + "Z"

                    span = {"name": "sim-node", "node_name": node_name}
                    if node_idx is not None:
                        span["idx"] = node_idx

                    log_entry = {
                        "timestamp": timestamp,
                        "level": "INFO",
                        "target": "netsim",
                        "fields": {"message": line, "node_name": node_name},
                        "spans": [span]
                    }

                    if node_id:
                        log_entry["fields"]["node_id"] = node_id

                    outfile.write(json.dumps(log_entry) + '\n')
                    total_lines += 1

    return total_lines

def create_summary_json(prefix, trace_id, session_id, nodes_info, start_time, end_time, event_count):
    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "info": {
            "name": prefix,
            "node_count": len(nodes_info),
            "expected_checkpoints": None
        },
        "stats": {
            "nodes": len(nodes_info),
            "log_lines": count_log_lines(prefix),
            "metric_updates": 0,
            "events": event_count
        },
        "nodes": nodes_info,
        "start_time": start_time,
        "checkpoints": [],
        "outcome": {
            "end_time": end_time,
            "result": {"Ok": None}
        }
    }

def count_log_lines(prefix):
    log_files = Path("logs").glob(f"{prefix}__*.txt")
    total = 0
    for log_file in log_files:
        with open(log_file) as f:
            total += sum(1 for line in f if line.strip() and not line.startswith('cmd:'))
    return total

def extract_nodes_info(prefix):
    log_files = sorted(Path("logs").glob(f"{prefix}__*.txt"))
    nodes = []
    for idx, log_file in enumerate(log_files):
        node_name = log_file.stem.replace(f"{prefix}__", "")
        node_id = extract_node_id_from_log(log_file)
        if node_id:
            nodes.append({"idx": idx, "label": node_name, "node_id": node_id, "name": node_name})
    return nodes

def get_time_range_from_logs(prefix):
    """Extract min/max timestamps from log files"""
    log_files = list(Path("logs").glob(f"{prefix}__*.txt"))
    min_time = None
    max_time = None

    for log_file in log_files:
        with open(log_file) as f:
            for line in f:
                ts = extract_timestamp_from_log_line(line)
                if ts:
                    if min_time is None or ts < min_time:
                        min_time = ts
                    if max_time is None or ts > max_time:
                        max_time = ts

    if min_time and max_time:
        return (min_time, max_time)

    # Fallback to now
    now = datetime.utcnow().isoformat() + "Z"
    return (now, now)

def convert_to_trace(prefix, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    trace_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    nodes_info = extract_nodes_info(prefix)
    print(f"Converting {prefix}: found {len(nodes_info)} nodes")

    # Get time range from actual log timestamps
    start_time, end_time = get_time_range_from_logs(prefix)

    # Logs
    log_count = convert_logs_to_jsonnd(prefix, output_path / "logs.jsonnd", nodes_info)
    print(f"  Logs: {log_count} lines")

    # Events
    parsed_events = parse_events_from_logs(prefix, nodes_info)
    print(f"  Events: {len(parsed_events)} captured")

    # Summary
    summary_data = create_summary_json(prefix, trace_id, session_id, nodes_info, start_time, end_time, len(parsed_events))
    with open(output_path / "summary.json", 'w') as f:
        json.dump(summary_data, f, indent=2)

    # Metrics
    try:
        subprocess.run([
            "python3", "convert_metrics.py",
            prefix, str(output_path / "metrics.sqlite"), trace_id
        ], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Events - already parsed above, just write to file
    events_data = {
        "events": parsed_events,
        "nodes": [{"idx": n["idx"], "label": n["label"], "node_idx": n["idx"]} for n in nodes_info]
    }
    with open(output_path / "events.json", 'w') as f:
        json.dump(events_data, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <sim_prefix> <output_dir>")
        sys.exit(1)
    convert_to_trace(sys.argv[1], sys.argv[2])
