import argparse
import json
import time

from mininet.net import Mininet
from mininet.util import dumpNodeConnections
from mininet.cli import CLI
from mininet.log import setLogLevel

from parser import stats_parser
from network import StarTopo
    
def run(nodes, prefix):
    topo = StarTopo(nodes=nodes)
    net = Mininet(topo = topo, waitConnected=True)
    net.start()
    print( "Dumping host connections" )
    dumpNodeConnections(net.hosts)
    print( "Testing network connectivity" )
    net.pingAll()

    p_box = []

    node_counts = {}
    node_ips = {}

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
            p = n.popen(cmd, stdout=f, stderr=f, shell=True)
            p_box.append(p)
        time.sleep(node['wait'])

    # CLI(net)
    for p in p_box:
        p.terminate()
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')

    parser = argparse.ArgumentParser()
    parser.add_argument("cfg", help = "Input config file")
    args = parser.parse_args()
    config_f = open(args.cfg)
    config = json.load(config_f)
    print('start test\n')

    for case in config['cases']:
        prefix = case['name']
        nodes = case['nodes']
        print('running "%s"...' % prefix)
        run(nodes, prefix)
        stats_parser(nodes, prefix)

    # # n_server = 2
    # # n_client = 6
    # # server_cmd = 'chuck http-server 1'
    # # client_cmd = 'hey -z 15s -c 1 -h2 -T application/octet-stream https://%s/128MB.bin'
    # # prefix = 'axum_'
    # # timeout = 20
    # load_time = 3
    
    # run(n_server, n_client, server_cmd, client_cmd, prefix, timeout, load_time)