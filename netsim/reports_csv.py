import argparse
import json
import os

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

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", help = "commit hash")
    parser.add_argument("--prom", help = "generate output for prometheus", action='store_true')
    parser.add_argument("--table", help = "generate output for github comments", action='store_true')
    args = parser.parse_args()

    files = []
    for root, dirs, fs in os.walk('report'):
        for f in fs:
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
        throughput = json_d['sum']['mbits']
        if not args.prom:
            throughput /= 1000
        throughput = float("{:.2f}".format(throughput))
        res[name][case] = throughput

    if args.prom:
        res_to_prom(res, args.commit)
    elif args.table:
        res_to_table(res)
    else:
        print(json.dumps(res, indent=4, sort_keys=True))