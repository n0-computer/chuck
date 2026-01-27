import json
import re
import os
import humanfriendly

invalid_results = {
    "data_len": 0,
    "elapsed": 0,
    "mbits": -1.0,
    "reported_mbits": 0,
    "reported_time": 0,
}


def parse_iroh_json_output(lines):
    """Parse iroh JSON output (NDJSON) and extract transfer stats."""
    for line in lines:
        try:
            data = json.loads(line.strip())
            if data.get("kind") == "DownloadComplete":
                size = data["size"]
                duration_us = data["duration"]
                elapsed = duration_us / 1_000_000.0
                mbits = (size * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
                return {
                    "data_len": size,
                    "elapsed": elapsed,
                    "mbits": mbits,
                    "reported_mbits": mbits,
                    "reported_time": elapsed,
                }
        except (json.JSONDecodeError, KeyError):
            continue
    raise Exception("No DownloadComplete event found in JSON output")


def parse_magic_iroh_client_json(lines):
    """Parse iroh JSON output for integration test results."""
    s = {
        "conn_upgrade": "false",
        "transfer_success": "false",
        "final_conn_direct": "false",
        "conn_events": 0,
    }
    for line in lines:
        try:
            data = json.loads(line.strip())
            kind = data.get("kind")
            if kind == "DownloadComplete":
                s["transfer_success"] = "true"
            elif kind == "ConnectionTypeChanged":
                s["conn_events"] = s["conn_events"] + 1
                status = data.get("status")
                addr = data.get("addr")
                is_direct = status == "Selected" and addr and "Ip" in addr
                if is_direct:
                    s["conn_upgrade"] = "true"
                    s["final_conn_direct"] = "true"
                else:
                    s["final_conn_direct"] = "false"
        except (json.JSONDecodeError, KeyError):
            continue
    return s


def parse_time_output(lines, size):
    """Parse time output and calculate throughput. (DEPRECATED - use JSON parsers)"""
    for line in lines:
        if line.startswith("real"):
            k = line[5:].strip()
            k = k.split("m")
            mins = int(k[0])
            sec = float(k[1][:-1])
            elapsed = mins * 60 + sec
            return {
                "data_len": size,
                "elapsed": elapsed,
                "mbits": size * 8 / (elapsed * 1e6),
                "reported_mbits": 0,
                "reported_time": 0,
            }
    return invalid_results


def parse_iroh_output(lines, size):
    """Parse iroh text output and calculate throughput. (DEPRECATED - use parse_iroh_json_output)"""
    transfer_lines = [
        line
        for line in lines
        if ("Transferred" in line or "Received" in line) and "in" in line and "/s" in line
    ]
    if not transfer_lines:
        raise Exception("bad run")

    reported = parse_humanized_output(transfer_lines[-1])
    reported_time = (size * 8) / (reported * 1_000_000)

    s = parse_time_output(lines, size)
    s["reported_mbits"] = reported
    s["reported_time"] = reported_time
    return s


def parse_humanized_output(line):
    """Convert human-readable size to megabits."""
    x = re.search("\((.*)\/s", line)
    if x is None:
        raise Exception("Line does not match bytesize pattern")

    match = x.groups()[0]
    bytes_size = humanfriendly.parse_size(match, binary=True)
    return bytes_size * 8 / 1e6


def parse_iperf(lines):
    """Generic parser for iperf server output."""
    stats = []
    collect = False
    for line in lines:
        if line.startswith("[ ID]"):
            collect = True
            continue
        if collect and "datagram" not in line:
            parts = [x for x in line.split() if x]
            p = parts.index("sec")
            transfer = float(parts[p + 1]) * {
                "KBytes": 1024,
                "MBytes": 1024**2,
                "GBytes": 1024**3,
            }.get(parts[p + 2], 1)
            throughput = float(parts[p + 3]) * (
                1000 if "Gbits/sec" == parts[p + 4].strip() else 1
            )
            stats.append({"data_len": transfer, "elapsed": 10.0, "mbits": throughput})
    return stats


def parse_magic_iroh_client(lines):
    """Parse magic iroh client integration logs. (DEPRECATED - use parse_magic_iroh_client_json)"""
    s = {"conn_upgrade": "false", "transfer_success": "false"}
    s["transfer_success"] = (
        "true"
        if any(
            "Received" in line and "in" in line and "/s" in line for line in lines
        )
        else "false"
    )
    s["conn_upgrade"] = (
        "true" if any(("conn_type::changed" in line and "Direct" in line) for line in lines) else "false"
    )
    return s


def aggregate_stats(stats):
    """Aggregate and average stats."""
    summed = {k: sum(d[k] for d in stats) for k in stats[0]}
    avg = {k: summed[k] / len(stats) for k in summed}
    return summed, avg


def write_report(prefix, name, stats):
    """Write stats to a report file."""
    summed, avg = aggregate_stats(stats)
    report = {"raw": stats, "sum": summed, "avg": avg}
    with open(f"report/{prefix}__{name}.json", "w") as f:
        json.dump(report, f, indent=4)


def process_logs(nodes, prefix, runner_id):
    """Process logs based on provided nodes and parsers."""
    valid_parsers = {
        "iperf_server": parse_iperf,
        "iperf_udp_server": parse_iperf,
        # DEPRECATED text-based parsers (kept for backwards compatibility)
        "time_1gb": lambda lines: [parse_time_output(lines, 1024 * 1024 * 1024)],
        "iroh_1gb": lambda lines: [parse_iroh_output(lines, 1024 * 1024 * 1024)],
        "iroh_1mb": lambda lines: [parse_iroh_output(lines, 1024 * 1024)],
        "iroh_cust_": lambda lines, size: [parse_iroh_output(lines, size)],
        # JSON-based parsers (preferred)
        "iroh_json": lambda lines: [parse_iroh_json_output(lines)],
    }
    for node in nodes:
        parser_name = node.get("parser", "")
        is_valid = (
            parser_name in valid_parsers
            or parser_name.startswith("iroh_cust_")
            or parser_name.startswith("iroh_json")
        )
        if "parser" in node and is_valid:
            stats = []
            for i in range(int(node["count"])):
                log_path = f'logs/{prefix}__{node["name"]}_{i}_r{runner_id}.txt'
                try:
                    with open(log_path, "r") as f:
                        lines = f.readlines()
                        if parser_name.startswith("iroh_cust_"):
                            size = humanfriendly.parse_size(
                                parser_name.split("_")[-1], binary=True
                            )
                            parser_func = valid_parsers["iroh_cust_"]
                            stats.extend(parser_func(lines, size))
                        elif parser_name.startswith("iroh_json"):
                            parser_func = valid_parsers["iroh_json"]
                            stats.extend(parser_func(lines))
                        else:
                            parser_func = valid_parsers[parser_name]
                            stats.extend(parser_func(lines))
                except Exception as e:
                    print(f"Error processing {log_path}: {e}")
                    stats = [invalid_results]
            write_report(prefix, node["name"], stats)


def process_integration_logs(nodes, prefix, runner_id):
    """Process integration logs based on nodes and valid parsers."""
    valid_parsers = {
        # DEPRECATED text-based parser (kept for backwards compatibility)
        "magic_iroh_client": parse_magic_iroh_client,
        # JSON-based parser (preferred)
        "magic_iroh_client_json": parse_magic_iroh_client_json,
    }
    for node in nodes:
        if "integration" in node and node["integration"] in valid_parsers:
            stats = []
            for i in range(int(node["count"])):
                log_path = f'logs/{prefix}__{node["name"]}_{i}_r{runner_id}.txt'
                try:
                    with open(log_path, "r") as f:
                        lines = f.readlines()
                        parser_func = valid_parsers[node["integration"]]
                        s = parser_func(lines)
                        s["node"] = f"{prefix}__{node['name']}_{i}"
                        stats.append(s)
                except Exception:
                    stats = []
            write_integration_report(prefix, node["name"], stats)


def write_integration_report(prefix, name, stats):
    """Write integration report to file."""
    with open(f"report/integration_{prefix}__{name}.json", "w") as f:
        json.dump(stats, f, indent=4)
