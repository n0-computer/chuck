import json
import os

def parse_time_output(lines, size):
    for line in lines:
        if line.startswith('real'):
            k = line[5:].strip()
            k = k.split('m')
            mins = int(k[0])
            sec = float(k[1][:-1])
            d = mins * 60 + sec
            s = {
                'data_len': size,
                'elapsed': d,
                'mbits': float(size * 8) / (d * 1000 * 1000)
            }
            return s

def parse_iperf_udp_server(lines):
    s = []
    collect = False
    for line in lines:
        if line.startswith('[ ID]'):
            collect = True
            continue
        if collect:
            if 'datagram' in line:
                continue
            k = line.split(' ')
            k = [x for x in k if x != '']
            p = k.index('sec')
            transfer = float(k[p+1])
            if k[p+2] == 'GBytes':
                transfer *= 1024 * 1024 * 1024
            if k[p+2] == 'MBytes':
                transfer *= 1024 * 1024
            if k[p+2] == 'KBytes':
                transfer *= 1024
            throughput = float(k[p+3])
            if k[p+4].strip() == 'Gbits/sec':
                throughput *= 1000
            stat = {}
            stat['data_len'] = transfer
            stat['elapsed'] = float(10.0)
            stat['mbits'] = throughput
            s.append(stat)
    return s

def parse_sendme_client(lines):
    s = {}
    for line in lines:
        if line.startswith('Stats'):
            k = line.replace('Stats ', '')
            k = k.replace('data_len', '"data_len"')
            k = k.replace('elapsed', '"elapsed"')
            k = k.replace('s,', ',')
            k = k.replace('mbits', '"mbits"')
            d = json.loads(k)
            s['data_len'] = int(d['data_len'])
            s['elapsed'] = float(d['elapsed'])
            s['mbits'] = float(d['mbits'])
    return s

def parse_iperf_server(lines):
    s = []
    collect = False
    for line in lines:
        if line.startswith('[ ID]'):
            collect = True
            continue
        if collect:
            k = line.split(' ')
            k = [x for x in k if x != '']
            p = k.index('sec')
            transfer = float(k[p+1])
            if k[p+2] == 'GBytes':
                transfer *= 1024 * 1024 * 1024
            if k[p+2] == 'MBytes':
                transfer *= 1024 * 1024
            if k[p+2] == 'KBytes':
                transfer *= 1024
            throughput = float(k[p+3])
            if k[p+4].strip() == 'Gbits/sec':
                throughput *= 1000
            stat = {}
            stat['data_len'] = transfer
            stat['elapsed'] = float(10.0)
            stat['mbits'] = throughput
            s.append(stat)
    return s

def aggregate_stats(stats):
    summed = {}
    for s in stats:
        for k, v in s.items():
            if k in summed:
                summed[k] += v
            else:
                summed[k] = v
    avrged = {}
    for k, v in summed.items():
        avrged[k] = float(v) / len(stats)
    return (summed, avrged)

def stats_parser(nodes, prefix):
    files = []
    valid_parsers = ['sendme_client', 'iperf_server', 'iperf_udp_server', 'time_1gb']
    for root, dirs, fs in os.walk('logs'):
        for f in fs:
            if f.startswith(prefix + '__'):
                files.append(os.path.join(root,f))
    for node in nodes:
        if 'parser' in node:
            stats = []
            if node['parser'] in valid_parsers:
                for i in range(int(node['count'])):
                    log_path = 'logs/%s__%s_%d.txt' %(prefix, node['name'], i)
                    f = open(log_path, 'r')
                    lines = f.readlines()
                    if node['parser'] == 'sendme_client':
                        s = parse_sendme_client(lines)
                        stats.append(s)
                    if node['parser'] == 'iperf_server':
                        s = parse_iperf_server(lines)
                        stats.extend(s)
                    if node['parser'] == 'iperf_udp_server':
                        s = parse_iperf_udp_server(lines)
                        stats.extend(s)
                    if node['parser'] == 'time_1gb':
                        s = parse_time_output(lines, 1024*1024*1024)
                        stats.append(s)
            (sum_stats, avg_stats) = aggregate_stats(stats)
            report = {
                'raw': stats,
                'sum': sum_stats,
                'avg': avg_stats
            }
            report_json = json.dumps(report, indent=4)
            f = open("report/%s_%s.json" % (prefix, node['name']), "w")
            f.write(report_json)
            f.close()