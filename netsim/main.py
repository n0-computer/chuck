import argparse
import concurrent.futures
import glob
import json
import os
import sys
import tempfile
import time

from mininet.log import setLogLevel, info, error
from mininet.net import Mininet

from net.link import TCLink
from net.network import StarTopo
from parsing.netsim import process_logs, process_integration_logs
from sniffer.sniff import Sniffer
from sniffer.process import run_viz
from util import cleanup_tmp_dirs, eject

TIMEOUT = 60 * 5


def setup_env_vars(prefix, node_name, temp_dir, node_env, debug=False, json_logs=False):
    env_vars = os.environ.copy()
    env_vars["RUST_LOG_STYLE"] = "never"
    env_vars["SSLKEYLOGFILE"] = f"./logs/keylog_{prefix}_{node_name}.txt"
    env_vars["IROH_DATA_DIR"] = f"{temp_dir}"

    if debug:
        env_vars["RUST_LOG"] = "debug"
    if not "RUST_LOG" in env_vars:
        env_vars["RUST_LOG"] = "warn"
    env_vars["RUST_LOG"] += ",iroh::_events::conn_type=trace"

    for key, value in node_env.items():
        env_vars[key] = value
    return env_vars


def parse_node_params(node, prefix, node_params, runner_id):
    """Parse parameters from node logs with validation."""
    parsed_params = {}
    wait_time = node.get("wait", 1)
    parser_type = node["param_parser"]
    expected_nodes = []

    # Wait for parameters to be available
    for _ in range(wait_time):
        time.sleep(1)
        for i in range(int(node["count"])):
            node_name = f'{node["name"]}_{i}_r{runner_id}'
            expected_nodes.append(node_name)
            log_file = f"logs/{prefix}__{node_name}.txt"

            if not os.path.exists(log_file):
                error(f"Warning: Log file not found: {log_file}")
                continue

            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    for idx, line in enumerate(lines):
                        # Parser 1: Simple ticket (used in lossy/standard sims)
                        if parser_type == "iroh_ticket" and line.startswith("All-in-one ticket"):
                            parsed_params[node_name] = line[len("All-in-one ticket: "):].strip()
                            break
                        # Parser 2: Endpoint with addresses (used in iroh/integration sims)
                        if parser_type == "iroh_endpoint_with_addrs" and line.startswith("Endpoint id:"):
                            if idx + 1 >= len(lines):
                                break
                            endpoint_id = lines[idx + 1].strip()
                            direct_addrs = []
                            j = idx + 2
                            if j < len(lines) and lines[j].startswith("Direct addresses:"):
                                j += 1
                                while j < len(lines) and lines[j].startswith("\t"):
                                    direct_addrs.append(lines[j].strip())
                                    j += 1
                            parsed_params[node_name] = {
                                "endpoint_id": endpoint_id,
                                "direct_addrs": direct_addrs
                            }
                            break
            except Exception as e:
                error(f"Error parsing parameters from {log_file}: {e}")

    # Validate that all expected parameters were found
    missing_params = [n for n in expected_nodes if n not in parsed_params]
    if missing_params:
        error("\n" + "=" * 80 + "\n")
        error(f"ERROR: Failed to parse required parameters using '{parser_type}'\n")
        error(f"Missing parameters for nodes: {', '.join(missing_params)}\n")
        error(f"Check the log files to ensure nodes are outputting expected format:\n")
        for node_name in missing_params:
            error(f"  - logs/{prefix}__{node_name}.txt\n")
        error("=" * 80 + "\n")

    return parsed_params


def terminate_processes(p_box):
    """Gracefully terminate processes, then forcefully kill if needed."""
    for p, cmd in p_box:
        error(f"Terminating process: {p.pid} {cmd[:100]}\n")
        p.terminate()

    # Wait for processes to terminate gracefully
    time.sleep(2)

    # Force kill any remaining processes
    for p, cmd in p_box:
        if p.poll() is None:
            error(f"Force killing hung process: {p.pid} {cmd[:100]}\n")
            p.kill()


def monitor_short_processes(p_short_box, prefix):
    """Monitor short-lived processes with timeout and detailed error reporting."""
    process_errors = []
    start_time = time.time()

    # Monitor processes until all complete or timeout
    for _ in range(TIMEOUT):
        time.sleep(1)
        if not any(p.poll() is None for (_, p, _) in p_short_box):
            break

    elapsed_time = time.time() - start_time

    # Check results and handle timeouts
    for node_name, p, cmd in p_short_box:
        result = p.poll()
        if result is None:
            # Process timed out
            error(f"\nProcess timed out after {elapsed_time:.1f}s for node {node_name}\n")
            error(f"Command was: {cmd}\n")
            p.terminate()
            time.sleep(1)
            if p.poll() is None:
                error(f"Force killing timed out process for node {node_name}\n")
                p.kill()
            process_errors.append(
                f"TIMEOUT: Process '{node_name}' timed out after {elapsed_time:.1f}s. "
                f"Command: {cmd[:200]}"
            )
        elif result != 0:
            # Process failed
            error(f"\nProcess failed with exit code {result} for node {node_name}\n")
            error(f"Command was: {cmd}\n")
            log_file = f"logs/{prefix}__{node_name}.txt"
            error(f"Check log file for details: {log_file}\n")
            process_errors.append(
                f"FAILED: Process '{node_name}' exited with code {result}. "
                f"Command: {cmd[:200]}. "
                f"Check log: {log_file}"
            )

    return process_errors


def handle_connection_strategy(node, node_counts, i, runner_id, node_ips, node_params):
    """Build command with connection strategy, validating all required parameters."""
    cmd = node["cmd"]
    if "param" in node:
        if node["param"] == "id":
            cmd = cmd % i

    if "connect" not in node:
        return cmd

    strategy = node["connect"]["strategy"]
    if strategy in ("plain", "plain_with_id", "params", "params_with_direct_addr", "params_with_parsed_addrs"):
        node_name = node["connect"]["node"]
        if not (node_name in node_counts):
            raise ValueError(
                f"Connection target node '{node_name}' not found in simulation. "
                f"Available nodes: {', '.join(node_counts.keys())}"
            )
        cnt = node_counts[node_name]
        id = i % cnt
        connect_to = f"{node_name}_{id}_r{runner_id}"

        if connect_to not in node_ips:
            raise ValueError(
                f"Cannot connect to node '{connect_to}': node IP not found. "
                f"Node may have failed to start."
            )

        if strategy == "plain":
            ip = node_ips[connect_to]
            return cmd % ip
        if strategy == "plain_with_id":
            ip = node_ips[connect_to]
            return cmd % (ip, id)
        if strategy == "params":
            if connect_to not in node_params:
                raise ValueError(
                    f"Cannot connect to node '{connect_to}': required parameters not available. "
                    f"Node may have failed to output expected parameters."
                )
            param = node_params[connect_to]
            # Handle both string (old parsers) and dict (new iroh_endpoint_with_addrs parser)
            if isinstance(param, dict):
                param = param["endpoint_id"]
            return cmd % param
        if strategy == "params_with_direct_addr":
            if connect_to not in node_params:
                raise ValueError(
                    f"Cannot connect to node '{connect_to}': required parameters not available. "
                    f"Node may have failed to output expected parameters."
                )
            param = node_params[connect_to]
            ip = node_ips[connect_to]
            return cmd % (ip, param)
        if strategy == "params_with_parsed_addrs":
            if connect_to not in node_params:
                raise ValueError(
                    f"Cannot connect to node '{connect_to}': required parameters not available. "
                    f"Node may have failed to output expected parameters."
                )
            param_data = node_params[connect_to]
            if isinstance(param_data, dict):
                endpoint_id = param_data["endpoint_id"]
                direct_addrs = param_data.get("direct_addrs", [])
                # Use parsed direct address if available, otherwise construct from node IP
                if direct_addrs:
                    first_addr = direct_addrs[0]
                else:
                    # Fallback: use the node's IP from mininet (need to find the port)
                    # For now, return just endpoint ID and let discovery work
                    ip = node_ips[connect_to]
                    # Default QUIC port for iroh-transfer
                    first_addr = f"{ip}:11204"
                return cmd % (first_addr, endpoint_id)
            else:
                return cmd % param_data
    return cmd


def execute_node_command(cmd, prefix, node_name, n, env_vars):
    log_path = f"logs/{prefix}__{node_name}.txt"
    with open(log_path, "w+") as f:
        f.write(f"cmd: {cmd}\n\n")
        f.flush()
        return n.popen(cmd, stdout=f, stderr=f, shell=True, env=env_vars)


def get_node_ips(net, nodes, runner_id):
    node_ips = {}
    for node in nodes:
        for i in range(int(node["count"])):
            node_name = f'{node["name"]}_{i}_r{runner_id}'
            n = net.get(node_name)
            node_ips[node_name] = n.IP()
    return node_ips


def prep_net(net, prefix, sniff):
    sniffer = Sniffer(net=net, output="logs/" + prefix + ".pcap")
    ti = sniffer.get_topoinfo()
    info("Testing network connectivity")
    net.pingAll()

    info("Topology:", json.dumps(ti, indent=4))
    if sniff:
        info("Attaching sniffer")
        sniffer.start()
        with open(f"logs/{prefix}.topo.json", "w+") as f:
            f.write(json.dumps(ti, indent=4))
    return sniffer


def run_case(nodes, runner_id, prefix, args, debug=False, visualize=False):
    topo = StarTopo(nodes=nodes, runner_id=runner_id)
    net = Mininet(topo=topo, waitConnected=True, link=TCLink)
    net.start()
    sniffer = prep_net(net, prefix, args.sniff | visualize)

    p_box, p_short_box = [], []
    temp_dirs = []

    node_counts = {node["name"]: int(node["count"]) for node in nodes}
    node_ips = get_node_ips(net, nodes, runner_id)
    node_params = {}

    for node in nodes:
        for i in range(int(node["count"])):
            node_name = f'{node["name"]}_{i}_r{runner_id}'
            n = net.get(node_name)

            cmd = handle_connection_strategy(
                node, node_counts, i, runner_id, node_ips, node_params
            )

            temp_dir = tempfile.TemporaryDirectory(
                prefix="netsim", suffix=f"{prefix}_{node_name}_{runner_id}"
            )
            temp_dirs.append(temp_dir)

            node_env = node.get("env", {})
            env_vars = setup_env_vars(prefix, node_name, temp_dir.name, node_env, debug)

            p = execute_node_command(cmd, prefix, node_name, n, env_vars)
            if "process" in node and node["process"] == "short":
                p_short_box.append((node_name, p, cmd))
            else:
                p_box.append((p, cmd))

        if "param_parser" in node:
            node_params.update(parse_node_params(node, prefix, node_params, runner_id))
        elif "wait" in node:
            time.sleep(int(node["wait"]))

    # CLI(net)

    process_errors = monitor_short_processes(p_short_box, prefix)
    if process_errors:
        error("\n" + "=" * 80 + "\n")
        error("PROCESS ERRORS DETECTED:\n")
        error("=" * 80 + "\n")
        for err_msg in process_errors:
            error(err_msg + "\n")
        error("=" * 80 + "\n")
        if args.integration:
            eject(nodes, prefix, runner_id, temp_dirs)
        else:
            error("WARNING: Continuing despite errors (not in integration mode)\n")

    terminate_processes(p_box)
    cleanup_tmp_dirs(temp_dirs)
    return (net, sniffer)


def run(case, runner_id, name, skiplist, args):
    prefix = name + "__" + case["name"]
    if prefix in skiplist:
        print("Skipping:", prefix)
        return (None, None)
    if args.filter and case["name"] != args.filter:
        return (None, None)
    nodes = case["nodes"]
    viz = False
    if "visualize" in case:
        viz = case["visualize"] & args.visualize
    print('Running "%s"...' % prefix)
    n, s = (None, None)
    if not args.reports_only:
        (n, s) = run_case(nodes, runner_id, prefix, args, args.debug, viz)
    process_logs(nodes, prefix, runner_id)
    process_integration_logs(nodes, prefix, runner_id)
    if viz:
        viz_args = {
            "path": "logs/" + prefix + ".viz.pcap",
            "keylog": "logs/keylog_" + prefix + "_iroh_srv_0.txt",
            "topo": "logs/" + prefix + ".topo.json",
            "output": "viz/" + prefix + ".svg",
        }
        run_viz(viz_args)
    return (n, s)


def run_parallel(cases, name, skiplist, args, max_workers=4):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        chunks = [cases[i : i + max_workers] for i in range(0, len(cases), max_workers)]
        for chunk in chunks:
            futures = []
            r = []
            for i, case in enumerate(chunk):
                futures.append(executor.submit(run, case, i, name, skiplist, args))
            for future in concurrent.futures.as_completed(futures):
                try:
                    rx = future.result()
                    r.append(rx)
                except Exception as e:
                    print("Exception:", e)
                    sys.exit(1)
            for n, s in r:
                if n:
                    n.stop()
                if s:
                    s.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cfg", help="Input config file")
    parser.add_argument(
        "--reports-only",
        help="Run only report generation",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--integration",
        help="Run in integration test mode",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--sniff",
        help="Run sniffer to record all traffic",
        action="store_true",
        default=False,
    )
    parser.add_argument("--skip", help="Comma separated list of tests to skip")
    parser.add_argument("--filter", help="Filter to specific test case name")
    parser.add_argument(
        "--debug", help="Enable full debug logging", action="store_true", default=True
    )
    parser.add_argument(
        "--visualize", help="Enable visualization", action="store_true", default=False
    )
    parser.add_argument(
        "--max-workers", help="Max workers for parallel execution", type=int, default=1
    )
    parser.add_argument(
        "--netsim-log-level", help="Set log level for netsim", default="error"
    )
    args = parser.parse_args()

    setLogLevel(args.netsim_log_level)

    skiplist = args.skip.split(",") if args.skip else []

    paths = []
    if os.path.isdir(args.cfg):
        paths = [
            f for f in glob.glob(os.path.join(args.cfg, "**", "*.json"), recursive=True)
        ]
    else:
        paths.append(args.cfg)

    print("Args:", args)

    for path in paths:
        config_f = open(path, "r")
        config = json.load(config_f)
        config_f.close()
        name = config["name"]
        print(f"Start testing: %s\n" % path)
        run_parallel(config["cases"], name, skiplist, args, args.max_workers)

    print("Done")
