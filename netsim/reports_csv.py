import os
import json

files = []
for root, dirs, fs in os.walk('report'):
    for f in fs:
        files.append(os.path.join(root,f))

test_map = {
    'chuck_http': '',
    'chuck_tls': '',
    'iperf': '',
    'iperf_udp': '',
    'sendme': ''
}

size_map = ['1_to_1', '1_to_3', '1_to_5', '1_to_10', '2_to_2', '2_to_4', '2_to_6', '2_to_10']

res = {}

for k, v in test_map.items():
    res[k] = {}
    for s in size_map:
        res[k][s] = -1.0

for f in files:
    k = f.split('_')
    p = k.index('to')
    name = '_'.join(k[:p-1])
    name = name[len('report/'):]
    size = '_'.join(k[p-1:p+2])
    json_f = open(f, 'r')
    json_d = json.load(json_f)
    throughput = json_d['sum']['mbits'] / 1000
    throughput = float("{:.2f}".format(throughput))
    res[name][size] = throughput

print(json.dumps(res, indent=4))