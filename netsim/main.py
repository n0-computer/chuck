import argparse
import json
import subprocess
import tempfile
import time
import os

from mininet.net import Mininet
from sniff import Sniffer
from link import TCLink
from mininet.log import setLogLevel

from netsim_parser import stats_parser
from netsim_parser import integration_parser
from network import StarTopo
from process_sniff import run_viz

TIMEOUT = 60 * 5

def logs_on_error(nodes, prefix, code=1, message=None):
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
    print('[ERROR] Process has failed with code:', code)
    if message:
        print('[ERROR] Message:', message)

def run(nodes, prefix, args, debug=False, visualize=False):
    integration = args.integration
    topo = StarTopo(nodes=nodes)
    net = Mininet(topo = topo, waitConnected=True, link=TCLink)
    net.start()

    sniffer = Sniffer(net=net, output="logs/" + prefix + ".pcap")
    ti = sniffer.get_topoinfo()

    print( "Testing network connectivity" )
    net.pingAll()
    
    print("Topo:", json.dumps(ti, indent=4))
    # if args.sniff or visualize:
    #     print( "Attaching sniffer" )
    #     sniffer.start()
    #     f = open("logs/" + prefix + ".topo.json", "w+")
    #     f.write(json.dumps(ti, indent=4))
    #     f.close()

    time.sleep(1)

    env_vars = os.environ.copy()
    if debug:
        env_vars['RUST_LOG'] = 'debug'
    if not 'RUST_LOG' in env_vars:
        env_vars['RUST_LOG'] = 'warn'
    # magicsock::endpoint required for iroh integration tests
    env_vars['RUST_LOG'] += ",iroh_net::magicsock::node_map::endpoint=trace"
    

    p_box = []
    p_short_box = []

    node_counts = {}
    node_ips = {}
    node_params = {}

    temp_dirs = []

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
            # cleanup_run = subprocess.run("sudo rm -rf /root/.local/share/iroh", shell=True, capture_output=True)
            time.sleep(0.1)
            env_vars['SSLKEYLOGFILE']= './logs/keylog_%s_%s.txt' % (prefix, node_name)

            temp_dir = tempfile.TemporaryDirectory(prefix='netsim', suffix='{}_{}'.format(prefix, node_name))
            temp_dirs.append(temp_dir)
            env_vars['IROH_DATA_DIR'] = '{}'.format(temp_dir.name)
            
            f.write('cmd: %s\n\n' % cmd)
            f.flush()
            p = n.popen(cmd, stdout=f, stderr=f, shell=True, env=env_vars)
            if 'process' in node and node['process'] == 'short':
                p_short_box.append(p)
            else:
                p_box.append(p)
        if 'param_parser' in node:
            done_wait = False
            if not 'wait' in node:
                node['wait'] = 1
            for z in range(node['wait']):
                if done_wait:
                    break
                time.sleep(1)
                for zz in range(int(node['count'])):
                    found = 0
                    node_name = '%s_%d' % (node['name'], zz)
                    n = net.get(node_name)
                    f = open('logs/%s__%s.txt' % (prefix, node_name), 'r')
                    lines = f.readlines()
                    for line in lines:
                        if node['param_parser'] == 'iroh_ticket':
                            if line.startswith('All-in-one ticket'):
                                node_params[node_name] = line[len('All-in-one ticket: '):].strip()
                                found+=1
                                break
                    f.close()
                    if found == int(node['count']):
                        done_wait = True
                        break
        else:
            if 'wait' in node:
                time.sleep(int(node['wait']))

    # CLI(net)

    process_errors = []
    for i in range(TIMEOUT):
        time.sleep(1)
        
        r = p.poll()
        if r is None:
            p.terminate()
            process_errors.append('Process has timed out: %s' % prefix)
        elif r != 0:
            process_errors.append('Process has failed: %s with exit code: %d' % (prefix, r))
            break

        if not any(p.poll() is None for p in p_short_box):
            break

    if process_errors:
        for error in process_errors:
            print(error)
        logs_on_error(nodes, prefix)
        cleanup_tmp_dirs(temp_dirs)
        raise Exception('Netsim run failed')

    for p in p_box:
        p.terminate()
    net.stop()
    sniffer.close()

    cleanup_tmp_dirs(temp_dirs)

def cleanup_tmp_dirs(temp_dirs):
    for temp_dir in temp_dirs:
        temp_dir.cleanup()


if __name__ == '__main__':
    setLogLevel('info')

    parser = argparse.ArgumentParser()
    parser.add_argument("cfg", help = "Input config file")
    parser.add_argument("-r", help = "Run only report generation", action='store_true')
    parser.add_argument("--integration", help = "Run in integration test mode", action='store_true')
    parser.add_argument("--sniff", help = "Run sniffer to record all traffic", action='store_false')
    parser.add_argument("--skip", help = "Comma separated list of tests to skip")
    parser.add_argument("--debug", help = "Enable full debug logging", action='store_true')
    args = parser.parse_args()

    skiplist = []
    if args.skip:
        skiplist = args.skip.split(',')

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
            if prefix in skiplist:
                print("Skipping:", prefix)
                continue
            nodes = case['nodes']
            viz = False
            # ignore any viz config as we really don't use it
            # if 'visualize' in case:
            #     viz = case['visualize']
            print('running "%s"...' % prefix)
            if not args.r:
                run(nodes, prefix, args, args.debug, viz)
            stats_parser(nodes, prefix)
            integration_parser(nodes, prefix)
            if viz:
                viz_args = {
                    'path': 'logs/' + prefix + '.viz.pcap',
                    'keylog': 'logs/keylog_' + prefix +'_iroh_srv_0.txt',
                    'topo': 'logs/' + prefix + '.topo.json',
                    'output': 'viz/' + prefix + '.svg'
                }
                run_viz(viz_args)