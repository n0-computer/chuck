import os


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
    logs_on_error(nodes, prefix, runner_id)
    cleanup_tmp_dirs(temp_dirs)
    raise Exception("Netsim run failed: %s" % prefix)


def print_route_table(net, runner_id):
    router_name = "r0_" + str(runner_id)
    print("*** Routing Table on Router:\n")
    print(net[router_name].cmd("route"))
    print("*** r0 smcroute:\n")
    print(net[router_name].cmd("smcroutectl -I smcroute-" + router_name + " show"))
    print("*** Multicast ping:\n")
    print(net["zbox1-r" + str(runner_id)].cmd("ping -c 3 239.0.0.1"))
