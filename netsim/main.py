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
import json as json_module
from sniffer.sniff import Sniffer
from sniffer.process import run_viz
from util import cleanup_tmp_dirs, eject, FAILED_TESTS, write_failure_summary

TIMEOUT = 60 * 5


def configure_multi_nat_hosts(net, nodes, runner_id):
    """Configure second interface on multi_nat hosts after network start."""
    for node in nodes:
        if node["type"] != "multi_nat":
            continue
        for i in range(int(node["count"])):
            node_name = f'{node["name"]}_{i}_r{runner_id}'
            n = net.get(node_name)
            # Second interface needs IP configured
            nat2_subnet_idx = 100 + i * 2 + 1
            second_ip = f"192.168.{nat2_subnet_idx}.10/24"
            intfs = n.intfNames()
            if len(intfs) >= 2:
                second_intf = intfs[1]
                n.cmd(f"ip addr add {second_ip} dev {second_intf}")


def execute_action(net, node_name, action, runner_id):
    """Execute a network action on a node."""
    n = net.get(node_name)
    action_type = action["action"]
    intfs = n.intfNames()

    if action_type == "switch_route":
        # Switch default route from one NAT to another
        from_idx = action.get("from", 0)
        to_idx = action.get("to", 1)
        # Calculate NAT gateway IPs (based on node index extracted from name)
        parts = node_name.rsplit("_", 2)
        node_idx = int(parts[1])
        nat1_subnet_idx = 100 + node_idx * 2
        nat2_subnet_idx = 100 + node_idx * 2 + 1
        gw_ips = [f"192.168.{nat1_subnet_idx}.1", f"192.168.{nat2_subnet_idx}.1"]
        n.cmd("ip route del default")
        n.cmd(f"ip route add default via {gw_ips[to_idx]}")
        info(f"ACTION [{node_name}]: Switched route from {gw_ips[from_idx]} to {gw_ips[to_idx]}\n")

    elif action_type == "link_down":
        intf_idx = action.get("interface", 0)
        if intf_idx < len(intfs):
            n.cmd(f"ip link set {intfs[intf_idx]} down")
            info(f"ACTION [{node_name}]: Brought down {intfs[intf_idx]}\n")

    elif action_type == "link_up":
        intf_idx = action.get("interface", 0)
        if intf_idx < len(intfs):
            n.cmd(f"ip link set {intfs[intf_idx]} up")
            info(f"ACTION [{node_name}]: Brought up {intfs[intf_idx]}\n")

    elif action_type == "change_ip":
        intf_idx = action.get("interface", 0)
        new_ip = action["ip"]
        if intf_idx < len(intfs):
            n.cmd(f"ip addr flush dev {intfs[intf_idx]}")
            n.cmd(f"ip addr add {new_ip} dev {intfs[intf_idx]}")
            info(f"ACTION [{node_name}]: Changed {intfs[intf_idx]} IP to {new_ip}\n")


def schedule_actions(net, nodes, runner_id):
    """Return list of (delay, node_name, action) tuples sorted by delay."""
    scheduled = []
    for node in nodes:
        if "actions" not in node:
            continue
        for i in range(int(node["count"])):
            node_name = f'{node["name"]}_{i}_r{runner_id}'
            for action in node["actions"]:
                scheduled.append((action["delay"], node_name, action))
    return sorted(scheduled, key=lambda x: x[0])


def setup_env_vars(prefix, node_name, temp_dir, node_env, debug=False):
    env_vars = os.environ.copy()
    env_vars["RUST_LOG_STYLE"] = "never"
    env_vars["SSLKEYLOGFILE"] = f"./logs/keylog_{prefix}_{node_name}.txt"
    env_vars["IROH_DATA_DIR"] = f"{temp_dir}"
    if debug:
        env_vars["RUST_LOG"] = "debug"
    if not "RUST_LOG" in env_vars:
        env_vars["RUST_LOG"] = "warn"
    env_vars["RUST_LOG"] += ",iroh=trace"
    for key, value in node_env.items():
        env_vars[key] = value
    return env_vars


def parse_node_params(node, prefix, node_params, runner_id):
    """Parse parameters from node logs with validation using fast polling."""
    parsed_params = {}
    max_wait = node.get("wait", 1)
    parser_type = node["param_parser"]
    poll_interval = 0.2

    expected_nodes = [
        f'{node["name"]}_{i}_r{runner_id}'
        for i in range(int(node["count"]))
    ]

    max_iterations = max(1, int(max_wait / poll_interval))
    for iteration in range(max_iterations):
        for node_name in expected_nodes:
            if node_name in parsed_params:
                continue

            log_file = f"logs/{prefix}__{node_name}.txt"
            if not os.path.exists(log_file):
                continue

            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    for idx, line in enumerate(lines):
                        if parser_type == "iroh_ticket" and line.startswith("All-in-one ticket"):
                            parsed_params[node_name] = line[len("All-in-one ticket: "):].strip()
                            break
                        # DEPRECATED: use iroh_endpoint_json instead
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
                        if parser_type == "iroh_endpoint_json":
                            try:
                                data = json.loads(line.strip())
                                if data.get("kind") == "EndpointBound":
                                    parsed_params[node_name] = {
                                        "endpoint_id": data["endpoint_id"],
                                        "direct_addrs": data.get("direct_addresses", [])
                                    }
                                    break
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                error(f"Error parsing parameters from {log_file}: {e}")

        if all(n in parsed_params for n in expected_nodes):
            break
        time.sleep(poll_interval)

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


def terminate_processes(p_box, prefix):
    """Gracefully terminate processes, then forcefully kill if needed."""
    for node_name, p, cmd in p_box:
        error(f"Terminating [{prefix}__{node_name}]: {cmd[:80]}\n")
        p.terminate()

    time.sleep(0.5)

    for node_name, p, cmd in p_box:
        if p.poll() is None:
            error(f"Force killing [{prefix}__{node_name}]: {cmd[:80]}\n")
            p.kill()


def monitor_short_processes(p_short_box, prefix, net=None, scheduled_actions=None, runner_id=0):
    """Monitor short-lived processes with timeout and detailed error reporting."""
    process_errors = []
    start_time = time.time()
    scheduled_actions = scheduled_actions or []
    executed_actions = set()

    # Monitor processes until all complete or timeout (poll every 200ms)
    max_polls = TIMEOUT * 5
    for _ in range(max_polls):
        elapsed = time.time() - start_time

        # Execute any scheduled actions whose delay has passed
        for idx, (delay, node_name, action) in enumerate(scheduled_actions):
            if idx not in executed_actions and elapsed >= delay:
                if net:
                    execute_action(net, node_name, action, runner_id)
                executed_actions.add(idx)

        if not any(p.poll() is None for (_, p, _) in p_short_box):
            break
        time.sleep(0.2)

    elapsed_time = time.time() - start_time

    # Check results and handle timeouts
    for node_name, p, cmd in p_short_box:
        result = p.poll()
        if result is None:
            # Process timed out
            error(f"\nProcess timed out after {elapsed_time:.1f}s for node {node_name}\n")
            error(f"Command was: {cmd}\n")
            p.terminate()
            time.sleep(0.2)
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


def prep_net(net, nodes, prefix, sniff, runner_id):
    configure_multi_nat_hosts(net, nodes, runner_id)
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
    sniffer = prep_net(net, nodes, prefix, args.sniff | visualize, runner_id)

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
                p_box.append((node_name, p, cmd))

        if "param_parser" in node:
            node_params.update(parse_node_params(node, prefix, node_params, runner_id))
        elif "wait" in node:
            time.sleep(int(node["wait"]))

    # CLI(net)

    scheduled_actions = schedule_actions(net, nodes, runner_id)
    process_errors = monitor_short_processes(
        p_short_box, prefix, net, scheduled_actions, runner_id
    )
    if process_errors:
        error("\n" + "=" * 80 + "\n")
        error(f"PROCESS ERRORS DETECTED in {prefix}:\n")
        error("=" * 80 + "\n")
        for err_msg in process_errors:
            error(err_msg + "\n")
        error("=" * 80 + "\n")
        failure_entry = {"prefix": prefix, "errors": []}
        for err_msg in process_errors:
            if err_msg.startswith("TIMEOUT:"):
                node = err_msg.split("'")[1]
                reason = f"timeout after {TIMEOUT}s"
            elif err_msg.startswith("FAILED:"):
                node = err_msg.split("'")[1]
                code_start = err_msg.find("code ") + 5
                code_end = err_msg.find(".", code_start)
                reason = f"exit code {err_msg[code_start:code_end]}"
            else:
                node = "unknown"
                reason = err_msg[:50]
            failure_entry["errors"].append({"node": node, "reason": reason})
        FAILED_TESTS.append(failure_entry)
        if args.integration:
            eject(nodes, prefix, runner_id, temp_dirs)
        else:
            error("WARNING: Continuing despite errors (not in integration mode)\n")

    terminate_processes(p_box, prefix)
    cleanup_tmp_dirs(temp_dirs)
    return (net, sniffer)


def validate_integration_results(nodes, prefix, runner_id, args):
    """Validate integration results against node requirements."""
    for node in nodes:
        if "integration_require" not in node:
            continue
        requirements = node["integration_require"]
        report_path = f"report/integration_{prefix}__{node['name']}.json"
        try:
            with open(report_path, "r") as f:
                results = json_module.load(f)
            for result in results:
                for field, expected in requirements.items():
                    actual = result.get(field)
                    if str(actual).lower() != str(expected).lower():
                        node_name = result.get("node", node["name"])
                        error(f"\nINTEGRATION CHECK FAILED [{node_name}]: {field}={actual}, expected={expected}\n")
                        failure_entry = {
                            "prefix": prefix,
                            "errors": [{"node": node_name, "reason": f"{field}={actual}, expected={expected}"}]
                        }
                        FAILED_TESTS.append(failure_entry)
                        if args.integration:
                            raise Exception(f"Integration requirement failed: {field}={actual}, expected={expected}")
        except FileNotFoundError:
            error(f"Integration report not found: {report_path}\n")
        except Exception as e:
            error(f"Error validating integration results: {e}\n")
            raise


def run(case, runner_id, name, args):
    prefix = name + "__" + case["name"]
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
    validate_integration_results(nodes, prefix, runner_id, args)
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
    # Filter skipped cases before chunking for optimal parallelism
    filtered = []
    for case in cases:
        prefix = name + "__" + case["name"]
        if prefix in skiplist:
            print("Skipping:", prefix)
        else:
            filtered.append(case)

    if not filtered:
        return

    with concurrent.futures.ThreadPoolExecutor() as executor:
        chunks = [filtered[i : i + max_workers] for i in range(0, len(filtered), max_workers)]
        for chunk in chunks:
            futures = []
            r = []
            for i, case in enumerate(chunk):
                futures.append(executor.submit(run, case, i, name, args))
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

    write_failure_summary()
    print("Done")
