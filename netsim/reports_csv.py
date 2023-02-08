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

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", help = "commit hash")
    parser.add_argument("--prom", help = "generate output for prometheus", action='store_true')
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
    else:
        print(json.dumps(res, indent=4))