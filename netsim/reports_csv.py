import argparse
import os
from parsing.reports import *


def collect_files(integration_flag):
    files = []
    res = {}
    for root, _, fs in os.walk("report"):
        for f in fs:
            if integration_flag == f.startswith("integration_") and not f.startswith(
                "intg_"
            ):
                ff = os.path.join(root, f)
                files.append(ff)
                k = ff.split("__")
                name = k[0][len("report/") :]
                res[name] = {}
    return files, res


def update_integration_results(json_data, res, name, case):
    for itg in json_data:
        for ik, iv in itg.items():
            if ik == "node":
                continue
            vv = 1 if iv == "true" else 0
            res_key = f"{name}_{ik}"
            if res_key not in res:
                res[res_key] = {}
            res[res_key][case] = vv
    return res


def update_performance_results(json_data, res, name, case, prom_flag):
    throughput = json_data["sum"]["mbits"] / (1000 if not prom_flag else 1)
    reported_throughput = json_data["sum"]["reported_mbits"] / (
        1000 if not prom_flag else 1
    )
    reported_time = json_data["avg"]["reported_time"]
    elapsed = json_data["avg"]["elapsed"]

    res[name][case] = {
        "throughput": round(throughput, 2),
        "reported_throughput": round(reported_throughput, 2),
        "reported_time": round(reported_time, 2),
        "elapsed": round(elapsed, 2),
    }
    return res


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", help="commit hash")
    parser.add_argument(
        "--prom", help="generate output for prometheus", action="store_true"
    )
    parser.add_argument(
        "--table", help="generate output for github comments", action="store_true"
    )
    parser.add_argument(
        "--metro", help="generate output for perf.iroh.computer", action="store_true"
    )
    parser.add_argument(
        "--integration",
        help="generate output for integration files",
        action="store_true",
    )
    args = parser.parse_args()

    files, res = collect_files(args.integration)

    for f in files:
        k = f.split("__")
        name = k[0][len("report/") :]
        case = k[1]
        json_f = open(f, "r")
        json_d = json.load(json_f)
        if args.integration:
            res = update_integration_results(json_d, res, name, case)
        else:
            res = update_performance_results(json_d, res, name, case, args.prom)
    if args.prom:
        res_to_prom(res, args.commit)
    elif args.table:
        res_to_table(res)
    elif args.metro:
        res_to_metro(res, args.commit, args.integration)
    else:
        print(json.dumps(res, indent=4, sort_keys=True))
