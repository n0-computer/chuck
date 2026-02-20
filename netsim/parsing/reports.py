import json
import time


def format_labels(commit, name, case, commit_label=True):
    labels = f'name="{name}",case="{case}"'
    if commit_label and commit:
        labels += f',commit="{commit}"'
    return labels


def print_metric(name, labels, value):
    print(f"{name}{{{labels}}} {value:.4f}")


def res_to_prom(res, commit):
    for test_name, cases in res.items():
        for case, metrics in cases.items():
            labels = format_labels(commit, test_name, case)
            print_metric("throughput", labels, metrics["throughput"])
            print_metric("reported_throughput", labels, metrics["reported_throughput"])


case_order = [
    "1_to_1",
    "1_to_3",
    "1_to_5",
    "1_to_10",
    "2_to_2",
    "2_to_4",
    "2_to_6",
    "2_to_10",
]


def case_sort_key(case):
    if case in case_order:
        return case_order.index(case)
    else:
        case_order.append(case)
        return len(case_order) - 1


def res_to_table(res):
    print("| test | case | throughput_gbps | throughput_transfer |")
    print("| ---- | ---- | --------------- | ------------------- |")
    for test_name, cases in res.items():
        sorted_cases = sorted(cases.items(), key=lambda x: case_sort_key(x[0]))
        for case, metrics in sorted_cases:
            print(
                f"| {test_name} | {case} | {metrics['throughput']:.2f} | {metrics['reported_throughput']:.2f} |"
            )


def create_metric(commit, bucket, name, tag, value, timestamp):
    return {
        "commitish": commit[:7],
        "bucket": bucket,
        "name": name,
        "tag": tag,
        "value": value,
        "timestamp": timestamp,
    }


def res_to_metro(res, commit, integration):
    r = {"metrics": []}
    now = int(time.time())
    prefix = "integration" if integration else "iroh"
    bucket = "integration" if integration else "netsim"

    for test_name, cases in res.items():
        if not test_name.startswith(prefix):
            continue

        suffix = "_".join(
            test_name.split("_")[2:] if integration else test_name.split("_")[1:]
        )
        suffix = f".{suffix}" if suffix else ""

        for case, metrics in cases.items():
            name = (
                "_".join(test_name.split("_")[1:]) if integration else "throughput_gbps"
            )
            tag = f"{case}{suffix}"

            val = metrics
            if not integration:
                val = metrics["throughput"]

            r["metrics"].append(create_metric(commit, bucket, name, tag, val, now))
            if not integration:
                r["metrics"].append(
                    create_metric(
                        commit,
                        bucket,
                        "reported_throughput_gbps",
                        tag,
                        metrics["reported_throughput"],
                        now,
                    )
                )
                if suffix == "":
                    # Report times
                    r["metrics"].extend(
                        [
                            create_metric(
                                commit,
                                bucket,
                                "time",
                                f"{case}{suffix}.total",
                                metrics["elapsed"],
                                now,
                            ),
                            create_metric(
                                commit,
                                bucket,
                                "time",
                                f"{case}{suffix}.transfer",
                                metrics["reported_time"],
                                now,
                            ),
                            create_metric(
                                commit,
                                bucket,
                                "time",
                                f"{case}{suffix}.setup",
                                metrics["elapsed"] - metrics["reported_time"],
                                now,
                            ),
                        ]
                    )

    print(json.dumps(r, indent=4, sort_keys=True))
