import os

FAILED_TESTS = []


def write_failure_summary(output_path="logs/failed_tests.txt"):
    if not FAILED_TESTS:
        return
    with open(output_path, "w") as f:
        for failure in FAILED_TESTS:
            prefix = failure["prefix"]
            f.write(f"FAILED: {prefix}\n")
            for node_err in failure["errors"]:
                node_name = node_err["node"]
                reason = node_err["reason"]
                log_path = f"logs/{prefix}__{node_name}.txt"
                f.write(f"  - {node_name}: {reason}\n")
                f.write(f"    Log: {log_path}\n")
                if os.path.isfile(log_path):
                    f.write("    --- Last 10 lines ---\n")
                    try:
                        with open(log_path, "r") as lf:
                            lines = lf.readlines()
                            for line in lines[-10:]:
                                f.write(f"    {line.rstrip()}\n")
                    except Exception:
                        f.write("    [failed to read log]\n")
                f.write("\n")


def logs_on_error(nodes, prefix, runner_id, code=1, message=None):
    node_counts = {}
    for node in nodes:
        node_counts[node["name"]] = int(node["count"])
        for i in range(int(node["count"])):
            node_name = "%s_%d" % (node["name"], i)
            log_name = "logs/%s__%s_r%d.txt" % (prefix, node_name, runner_id)
            if os.path.isfile(log_name):
                print(
                    "\n################################################################"
                )
                print("\n[INFO] Log file: %s" % log_name)
                f = open(log_name, "r")
                lines = f.readlines()
                for line in lines:
                    print("[INFO][%s__%s] %s" % (prefix, node_name, line.rstrip()))
            else:
                print("[WARN] log file missing: %s" % log_name)
    print("[ERROR] Process has failed with code:", code)
    if message:
        print("[ERROR] Message:", message)


def cleanup_tmp_dirs(temp_dirs):
    for temp_dir in temp_dirs:
        temp_dir.cleanup()


def eject(nodes, prefix, runner_id, temp_dirs):
    write_failure_summary()
    cleanup_tmp_dirs(temp_dirs)
    raise Exception("Netsim run failed: %s" % prefix)
