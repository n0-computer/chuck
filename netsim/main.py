import argparse
import concurrent.futures
import glob
import json
import os
import sys
import tempfile
import time

from mininet.log import setLogLevel, info
from mininet.net import Mininet

from net.link import TCLink
from net.network import StarTopo
from parsing.netsim import process_logs, process_integration_logs
from sniffer.sniff import Sniffer
from sniffer.process import run_viz
from util import cleanup_tmp_dirs, eject

TIMEOUT = 60 * 5


def setup_env_vars(prefix, node_name, temp_dir, debug=False):
    env_vars = os.environ.copy()
    env_vars["RUST_LOG_STYLE"] = "never"
    env_vars["SSLKEYLOGFILE"] = f"./logs/keylog_{prefix}_{node_name}.txt"
    env_vars["IROH_DATA_DIR"] = f"{temp_dir}"
    if debug:
        env_vars["RUST_LOG"] = "debug"
    if not "RUST_LOG" in env_vars:
        env_vars["RUST_LOG"] = "warn"
    env_vars["RUST_LOG"] += ",iroh_net::magicsock::node_map::endpoint=trace"
    return env_vars


def parse_node_params(node, prefix, node_params, runner_id):
    node_params = {}
    wait_time = node.get("wait", 1)
    for _ in range(wait_time):
        time.sleep(1)
        for i in range(int(node["count"])):
            node_name = f'{node["name"]}_{i}_r{runner_id}'
            with open(f"logs/{prefix}__{node_name}.txt", "r") as f:
                for line in f:
                    if node["param_parser"] == "iroh_ticket" and line.startswith(
                        "All-in-one ticket"
                    ):
                        node_params[node_name] = line[
                            len("All-in-one ticket: ") :
                        ].strip()
                        break
    return node_params


def terminate_processes(p_box):
    for p in p_box:
        p.terminate()


def monitor_short_processes(p_short_box, prefix):
    process_errors = []
    for _ in range(TIMEOUT):
        time.sleep(1)
        if not any(p.poll() is None for (_, p) in p_short_box):
            break
    for node_name, p in p_short_box:
        result = p.poll()
        if result is None:
            p.terminate()
            process_errors.append(f"Process timeout: {prefix} for node {node_name}")
        elif result != 0:
            process_errors.append(
                f"Process failed: {prefix} with exit code {result} for node {node_name}"
            )
    return process_errors


def handle_connection_strategy(node, node_counts, i, runner_id, node_ips, node_params):
    cmd = node["cmd"]
    if "param" in node:
        if node["param"] == "id":
            cmd = cmd % i
    strategy = node["connect"]["strategy"]
    if strategy in ("plain", "plain_with_id", "params"):
        node_name = node["connect"]["node"]
        if not (node_name in node_counts):
            raise ValueError(f"Node not found for: {node_name}")
        cnt = node_counts[node_name]
        id = i % cnt
        connect_to = f"{node_name}_{id}_r{runner_id}"
        if connect_to not in node_ips:
            raise ValueError(f"Connecting node not found for: {connect_to}")
        if strategy == "plain":
            ip = node_ips[connect_to]
            return cmd % ip
        if strategy == "plain_with_id":
            ip = node_ips[connect_to]
            return cmd % (ip, id)
        if strategy == "params":
            param = node_params[connect_to]
            return cmd % param
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
            env_vars = setup_env_vars(prefix, node_name, temp_dir.name, debug)

            p = execute_node_command(cmd, prefix, node_name, n, env_vars)
            if "process" in node and node["process"] == "short":
                p_short_box.append((node_name, p))
            else:
                p_box.append(p)

        if "param_parser" in node:
            node_params.update(parse_node_params(node, prefix, node_params, runner_id))
        elif "wait" in node:
            time.sleep(int(node["wait"]))

    # CLI(net)

    process_errors = monitor_short_processes(p_short_box, prefix)
    if process_errors and args.integration:
        for error in process_errors:
            print(error)
        eject(nodes, prefix, runner_id, temp_dirs)

    terminate_processes(p_box)
    cleanup_tmp_dirs(temp_dirs)
    return (net, sniffer)


def run(case, runner_id, name, skiplist, args):
    prefix = name + "__" + case["name"]
    if prefix in skiplist:
        print("Skipping:", prefix)
        return
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
    parser.add_argument(
        "--debug", help="Enable full debug logging", action="store_true", default=False
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
