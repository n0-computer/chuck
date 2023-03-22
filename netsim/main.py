import argparse
import json
import time
import os

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.util import dumpNodeConnections
from mininet.cli import CLI
from mininet.log import setLogLevel

from parser import stats_parser
from network import StarTopo

TIMEOUT = 60 * 2

def logs_on_error(nodes, prefix):
    node_counts = {}
    for node in nodes:
        node_counts[node['name']] = int(node['count'])
        for i in range(int(node['count'])):
            node_name = '%s_%d' % (node['name'], i)
            log_name= 'logs/%s__%s.txt' % (prefix, node_name)
            if os.path.isfile(log_name):
                print('\n\n[INFO] Log file: %s' % log_name)
                f = open(log_name, 'r')
                lines = f.readlines()
                for line in lines:
                    print('[INFO][%s__%s] %s' % (prefix, node_name, line.rstrip()))
            else:
                print('[WARN] log file missing: %s' % log_name)
    pass
    
def run(nodes, prefix, integration, debug=False):
    topo = StarTopo(nodes=nodes)
    net = Mininet(topo = topo, waitConnected=True, link=TCLink)
    net.start()
    print( "Dumping host connections" )
    dumpNodeConnections(net.hosts)
    print( "Testing network connectivity" )
    net.pingAll()

    env_vars = os.environ.copy()
    if debug:
        env_vars['RUST_LOG'] = 'debug'

    p_box = []
    p_short_box = []

    node_counts = {}
    node_ips = {}
    node_params = {}

    for node in nodes:
        node_counts[node['name']] = int(node['count'])
        for i in range(int(node['count'])):
            node_name = '%s_%d' % (node['name'], i)
            f = open('logs/%s__%s.txt' % (prefix, node_name), 'w+')
            n = net.get(node_name)
            node_ips[node_name] = n.IP()
            cmd = node['cmd']
            if 'param' in node:
                if node['param'] == 'id':
                    cmd = cmd % i
            if node['connect']['strategy'] == 'plain':
                cnt = node_counts[node['connect']['node']]
                id = i % cnt
                connect_to = '%s_%d' % (node['connect']['node'], id)
                ip = node_ips[connect_to]
                cmd = cmd % ip
            if node['connect']['strategy'] == 'plain_with_id':
                cnt = node_counts[node['connect']['node']]
                id = i % cnt
                connect_to = '%s_%d' % (node['connect']['node'], id)
                ip = node_ips[connect_to]
                cmd = cmd % (ip, id)
            if node['connect']['strategy'] == 'params':
                cnt = node_counts[node['connect']['node']]
                id = i % cnt
                connect_to = '%s_%d' % (node['connect']['node'], id)
                param = node_params[connect_to]
                cmd = cmd % (param)
            p = n.popen(cmd, stdout=f, stderr=f, shell=True, env=env_vars)
            if 'process' in node and node['process'] == 'short':
                p_short_box.append(p)
            else:
                p_box.append(p)
        if 'wait' in node:
            time.sleep(node['wait'])
        if 'param_parser' in node:
            for i in range(int(node['count'])):
                node_name = '%s_%d' % (node['name'], i)
                n = net.get(node_name)
                f = open('logs/%s__%s.txt' % (prefix, node_name), 'r')
                lines = f.readlines()
                for line in lines:
                    if node['param_parser'] == 'iroh_ticket':
                        if line.startswith('All-in-one ticket'):
                            node_params[node_name] = line[len('All-in-one ticket: '):].strip()
                            break

    # CLI(net)
    for i in range(TIMEOUT):
        time.sleep(1)
        if not any(p.poll() is None for p in p_short_box):
            break
    for p in p_short_box:
        if integration:
            r = p.poll()
            if r is None:
                p.terminate()
                logs_on_error(nodes, prefix)
                raise Exception('Process has timed out')
            if r != 0:
                logs_on_error(nodes, prefix)
                raise Exception('Process has failed')
        else:
            p.terminate()
    for p in p_box:
        p.terminate()
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')

    parser = argparse.ArgumentParser()
    parser.add_argument("cfg", help = "Input config file")
    parser.add_argument("-r", help = "Run only report generation", action='store_true')
    parser.add_argument("--integration", help = "Run in integration test mode", action='store_true')
    args = parser.parse_args()

    paths = []
    is_dir = os.path.isdir(args.cfg)
    if is_dir:
        for root, dirs, files in os.walk(args.cfg):
            for f in files:
                if f.endswith('.json'):
                    paths.append(os.path.join(root, f))
    else:
        paths.append(args.cfg)
    
    for path in paths:    
        config_f = open(path, 'r')
        config = json.load(config_f)
        print('start test\n')
        name = config['name']

        for case in config['cases']:
            prefix = name + '__' + case['name']
            nodes = case['nodes']
            print('running "%s"...' % prefix)
            if not args.r:
                run(nodes, prefix, args.integration, True)
            stats_parser(nodes, prefix)