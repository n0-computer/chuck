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

def extract_node_id_from_log(log_file):
    with open(log_file) as f:
        for line in f:
            match = re.search(r'(?:Node ID|Endpoint id):\s*([a-z0-9]{52})', line, re.IGNORECASE)
            if match:
                return match.group(1)
    return None

def convert_logs_to_jsonnd(prefix, output_path):
    log_files = list(Path("logs").glob(f"{prefix}__*.txt"))

    with open(output_path, 'w') as outfile:
        for log_file in log_files:
            node_name = log_file.stem.replace(f"{prefix}__", "")
            node_id = extract_node_id_from_log(log_file)

            with open(log_file, 'r') as infile:
                for line in infile:
                    line = line.strip()
                    if not line or line.startswith('cmd:') or line.startswith('METRICS:'):
                        continue

                    log_entry = {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "level": "INFO",
                        "target": "netsim",
                        "fields": {"message": line, "node_name": node_name},
                        "spans": [{"name": "sim-node", "node_name": node_name}]
                    }

                    if node_id:
                        log_entry["fields"]["node_id"] = node_id

                    outfile.write(json.dumps(log_entry) + '\n')

def create_summary_json(prefix, trace_id, session_id, nodes_info):
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
            "events": 0
        },
        "nodes": nodes_info,
        "start_time": datetime.utcnow().isoformat() + "Z",
        "checkpoints": [],
        "outcome": {
            "end_time": datetime.utcnow().isoformat() + "Z",
            "result": {"Ok": []}
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
            nodes.append({"idx": idx, "name": node_name, "node_id": node_id})
    return nodes

def convert_to_trace(prefix, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    trace_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    nodes_info = extract_nodes_info(prefix)

    # Logs
    convert_logs_to_jsonnd(prefix, output_path / "logs.jsonnd")

    # Summary
    summary_data = create_summary_json(prefix, trace_id, session_id, nodes_info)
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

    # Events
    events_data = {
        "events": [],
        "nodes": [{"idx": n["idx"], "label": n["name"], "node_id": n["node_id"]} for n in nodes_info]
    }
    with open(output_path / "events.json", 'w') as f:
        json.dump(events_data, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <sim_prefix> <output_dir>")
        sys.exit(1)
    convert_to_trace(sys.argv[1], sys.argv[2])
