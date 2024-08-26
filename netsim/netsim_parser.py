import json
import os
import humanfriendly

invalid_results = {
                    'data_len': 0,
                    'elapsed': 0,
                    'mbits': -1.0,
                    'reported_mbits': 0,
                    'reported_time': 0,
                }

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
                'mbits': float(size * 8) / (d * 1000 * 1000),
                'reported_mbits': 0,
                'reported_time': 0,
            }
            return s
    return invalid_results

def parse_humanized_output(line):
    p = line.split(', ')[-1]
    v_bytes = humanfriendly.parse_size(p, binary=True)
    v_mbits = float(v_bytes*8) / (1024*1024)
    return v_mbits

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

def parse_iroh_client(lines):
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
    if not 'data_len' in s:
        return invalid_results
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
    valid_parsers = ['iroh_client', 'iperf_server', 'iperf_udp_server', 'time_1gb', 'iroh_1gb', 'iroh_cust_']
    for root, dirs, fs in os.walk('logs'):
        for f in fs:
            if f.startswith(prefix + '__'):
                files.append(os.path.join(root,f))
    for node in nodes:
        if 'parser' in node:
            stats = []
            try:
                if any(node['parser'].startswith(prefix) for prefix in valid_parsers):
                    for i in range(int(node['count'])):
                        log_path = 'logs/%s__%s_%d.txt' %(prefix, node['name'], i)
                        f = open(log_path, 'r')
                        lines = f.readlines()
                        if node['parser'] == 'iroh_client':
                            s = parse_iroh_client(lines)
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
                        if node['parser'] in ['iroh_1gb', 'iroh_1mb'] or node['parser'].startswith('iroh_cust_'):
                            is_ok = 0
                            reported = 0
                            reported_time = 0
                            f_size = 1024*1024*1024
                            if node['parser'] == 'iroh_1mb':
                                f_size = 1024*1024
                            if node['parser'].startswith('iroh_cust_'):
                                f_size_str = node['parser'].split('_')[-1]
                                f_size = humanfriendly.parse_size(f_size_str, binary=True)
                            for line in lines:
                                if 'Transferred' in line and 'in' in line and '/s' in line:
                                    is_ok += 1
                                    reported = parse_humanized_output(line)
                                    reported_time = (f_size*8) / (reported*1000*1000)
                            if is_ok == 0:
                                raise Exception("bad run")
                            s = parse_time_output(lines, f_size)
                            s['reported_mbits'] = reported
                            s['reported_time'] = reported_time
                            stats.append(s)
            except:
                stats = [{
                    'data_len': 0,
                    'elapsed': 0,
                    'mbits': -1.0
                }]
            (sum_stats, avg_stats) = aggregate_stats(stats)
            report = {
                'raw': stats,
                'sum': sum_stats,
                'avg': avg_stats
            }
            report_json = json.dumps(report, indent=4)
            f = open("report/%s__%s.json" % (prefix, node['name']), "w")
            f.write(report_json)
            f.close()

def parse_magic_iroh_client(lines):
    s = {
        'conn_upgrade': 'false',
        'transfer_success': 'false',
    }
    is_ok = 0
    for line in lines:
        if 'Transferred' in line and 'in' in line and '/s' in line:
            is_ok += 1
        if 'found send address' in line:
            s['conn_upgrade'] = 'true'
    s['transfer_success'] = 'true' if is_ok == 1 else 'false'
    return s

def integration_parser(nodes, prefix):
    files = []
    valid_parsers = ['magic_iroh_client']
    for root, dirs, fs in os.walk('logs'):
        for f in fs:
            if f.startswith(prefix + '__'):
                files.append(os.path.join(root,f))
    for node in nodes:
        if 'integration' in node:
            stats = []
            try:
                if node['integration'] in valid_parsers:
                    for i in range(int(node['count'])):
                        log_path = 'logs/%s__%s_%d.txt' % (prefix, node['name'], i)
                        f = open(log_path, 'r')
                        lines = f.readlines()
                        if node['integration'] == 'magic_iroh_client':
                            s = parse_magic_iroh_client(lines)
                            s['node'] = '%s__%s_%d' % (prefix, node['name'], i)
                            print(s)
                            stats.append(s)
            except:
                print("Integration error")
                stats = []

            report_json = json.dumps(stats, indent=4)
            f = open("report/integration_%s__%s.json" % (prefix, node['name']), "w")
            f.write(report_json)
            f.close()
