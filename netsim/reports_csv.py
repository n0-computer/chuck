import argparse
import json
import os
import time

def res_to_prom(res, commit):
    for k, v in res.items():
        for c, t in v.items():
            labels = 'name="%s",case="%s"' % (k, c)
            if commit:
                labels += ',commit="%s"' % commit
            print('throughput{%s} %f' % (labels, t))

case_order = ['1_to_1', '1_to_3', '1_to_5', '1_to_10', '2_to_2', '2_to_4', '2_to_6', '2_to_10']

def case_sort(x):
    if x[0] in case_order:
        return case_order.index(x[0])
    else:
        case_order.append(x[0])
        return len(case_order) - 1

def res_to_table(res):
    print('| test | case | throughput_gbps |')
    print('| ---- | ---- | ---------- |')
    for k, v in res.items():
        vl = [(g,h) for g,h in v.items()]
        vl = sorted(vl, key=case_sort)
        for c, t in vl:
            print('| %s | %s | %.2f |' % (k, c, t))

def res_to_metro(res, commit, integration):
    r = {
        "metrics": []
    }
    now = int( time.time() )
    keys = []
    prefix = 'iroh'
    if integration:
        prefix = 'integration'
    for k, v in res.items():
        if k.startswith(prefix):
            keys.append(k)

    for k in keys:
        v = res[k]
        suffix_p = k.split('_')
        suffix = '_'.join(suffix_p[1:])
        if integration:
            suffix = '_'.join(suffix_p[2:])
        if suffix != '':
            suffix = '.' + suffix
        nm = "throughput_gbps"
        if integration:
            nm = '_'.join(suffix_p[1:])
        bkt = "netsim"
        if integration:
            bkt = "integration"
        for c, t in v.items():
            m = {
                "commitish": commit[0:7],
                "bucket": bkt,
                "name": nm,
                "tag": '%s%s' % (c, suffix),
                "value": t,
                "timestamp": now
            }
            r["metrics"].append(m)
    print(json.dumps(r, indent=4, sort_keys=True))


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", help = "commit hash")
    parser.add_argument("--prom", help = "generate output for prometheus", action='store_true')
    parser.add_argument("--table", help = "generate output for github comments", action='store_true')
    parser.add_argument("--metro", help = "generate output for perf.iroh.computer", action='store_true')
    parser.add_argument("--integration", help = "generate output for integration files", action='store_true')
    args = parser.parse_args()

    files = []
    for root, dirs, fs in os.walk('report'):
        for f in fs:
            if args.integration != f.startswith('integration_'):
                continue
            files.append(os.path.join(root,f))

    test_map = {}
    case_map = {}

    # format: testname__case__node
    for f in files:
        k = f.split('__')
        name = k[0][len('report/'):]
        test_map[name] = ''
        case = k[1]

    res = {}

    for k, v in test_map.items():
        res[k] = {}
        for c in case_map:
            res[k][c] = -1.0

    for f in files:
        k = f.split('__')
        name = k[0][len('report/'):]
        case = k[1]
        json_f = open(f, 'r')
        json_d = json.load(json_f)
        if args.integration:
            for itg in json_d:
                for ik, iv in itg.items():
                    if ik == 'node':
                        continue
                    vv = iv == 'true'
                    if vv:
                        vv = 1
                    else:
                        vv = 0
                    if not name + "_" + str(ik) in res:
                        res[name + "_" + str(ik)] = {}
                    res[name + "_" + str(ik)][case] = vv
        else:
            throughput = json_d['sum']['mbits']
            if not args.prom:
                throughput /= 1000
            throughput = float("{:.2f}".format(throughput))
            res[name][case] = throughput
    if args.prom:
        res_to_prom(res, args.commit)
    elif args.table:
        res_to_table(res)
    elif args.metro:
        res_to_metro(res, args.commit, args.integration)
    else:
        print(json.dumps(res, indent=4, sort_keys=True))