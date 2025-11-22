#!/usr/bin/env python3
"""Convert netsim metrics to trace-server SQLite format."""

import sys
import json
import sqlite3
import re
from pathlib import Path
from datetime import datetime
import uuid

def create_metrics_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""CREATE TABLE IF NOT EXISTS metrics (
        id BLOB PRIMARY KEY, name TEXT NOT NULL, group_name TEXT NOT NULL,
        project_id BLOB NOT NULL, node_id BLOB NOT NULL, description TEXT,
        UNIQUE(project_id, name, node_id))""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS metric_abs_events (
        metric_id BLOB NOT NULL, ts TEXT NOT NULL, abs_value INTEGER NOT NULL,
        FOREIGN KEY(metric_id) REFERENCES metrics(id))""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS metric_counter_incs (
        metric_id BLOB NOT NULL, ts TEXT NOT NULL, increase INTEGER NOT NULL,
        FOREIGN KEY(metric_id) REFERENCES metrics(id))""")

    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_metric_abs_events_metric_ts
        ON metric_abs_events(metric_id, ts)""")

    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_metric_counter_incs_metric_ts
        ON metric_counter_incs(metric_id, ts)""")

    conn.commit()
    return conn

def node_id_to_bytes(node_id_hex):
    return bytes.fromhex(node_id_hex)

def parse_metrics_from_logs(prefix):
    all_metrics = []
    for log_file in Path("logs").glob(f"{prefix}__*.txt"):
        node_name = log_file.stem.replace(f"{prefix}__", "")
        with open(log_file) as f:
            for line in f:
                if line.startswith(('METRICS:', 'PROGRESS:')):
                    try:
                        prefix_len = 8 if line.startswith('METRICS:') else 9
                        metric_data = json.loads(line[prefix_len:])
                        metric_data['_node_name'] = node_name
                        all_metrics.append(metric_data)
                    except json.JSONDecodeError:
                        pass
    return all_metrics

def insert_metrics(conn, trace_id, metrics_list):
    cursor = conn.cursor()
    trace_id_bytes = uuid.UUID(trace_id).bytes
    metrics_created = set()

    for metric_data in metrics_list:
        node_id_hex = metric_data.get('node_id')
        if not node_id_hex:
            continue

        try:
            node_id_bytes = node_id_to_bytes(node_id_hex)
        except ValueError:
            continue

        timestamp = datetime.utcfromtimestamp(metric_data.get('timestamp')).isoformat() + "Z"

        for metric_name, value in metric_data.items():
            if metric_name in ['timestamp', 'timestamp_rfc3339', 'node_id', '_node_name', '_type']:
                continue
            if not isinstance(value, (int, float)):
                continue

            metric_key = (trace_id, metric_name, node_id_hex)
            if metric_key not in metrics_created:
                metric_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{trace_id}:{metric_name}:{node_id_hex}").bytes
                cursor.execute("INSERT OR IGNORE INTO metrics (id, name, group_name, project_id, node_id, description) VALUES (?, ?, ?, ?, ?, ?)",
                    (metric_id, metric_name, "transfer", trace_id_bytes, node_id_bytes, metric_name))
                metrics_created.add(metric_key)
            else:
                metric_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{trace_id}:{metric_name}:{node_id_hex}").bytes

            cursor.execute("INSERT INTO metric_abs_events (metric_id, ts, abs_value) VALUES (?, ?, ?)",
                (metric_id, timestamp, int(value)))

    conn.commit()

def convert_metrics(prefix, output_db_path, trace_id):
    conn = create_metrics_db(output_db_path)
    metrics_list = parse_metrics_from_logs(prefix)
    if metrics_list:
        insert_metrics(conn, trace_id, metrics_list)
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <sim_prefix> <output_db_path> <trace_id>")
        sys.exit(1)
    convert_metrics(sys.argv[1], sys.argv[2], sys.argv[3])
