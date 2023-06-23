from mininet.topo import Topo
from mininet.nodelib import NAT

"""
Default network layout:
        h0    h1
          \  /
           s1 - hN...
"""
class StarTopo(Topo):
    "Single switch connected to n hosts."
    def build(self, nodes=[{'name': 'hx', 'count': 1, 'type': 'public'}, {'name': 'h', 'count': 1, 'type': 'public'}], interconnect='s1'):
        interconnect = self.addSwitch(interconnect)
        kk = 0
        for node in nodes:
            if node['type'] == 'public':
                for i in range(int(node['count'])):
                    h = self.addHost('%s_%d' % (node['name'], i))
                    if 'link' in node:
                        loss = node['link']['loss']
                        latency = node['link']['latency']
                        bw = node['link']['bw']
                        self.addLink(interconnect, h, loss=loss, delay=latency, bw=bw)
                    else:
                        self.addLink(interconnect, h)
                    
            if node['type'] == 'nat':
                kk+=1
                for i in range(int(node['count'])):
                    inetIntf = 'n_%s%d-e0' % (node['name'], i)
                    localIntf = 'n_%s%d-e1' % (node['name'], i)
                    localIP = '192.168.%d.1' % i
                    localSubnet = '192.168.%d.0/24' % i
                    natParams = { 'ip' : '%s/24' % localIP }
                    # add NAT to topology
                    nat = self.addNode('n_%s%d' % (node['name'], i), cls=NAT, subnet=localSubnet,
                                    inetIntf=inetIntf, localIntf=localIntf)
                    switch = self.addSwitch('natsw%s%d' % (node['name'][:2], i))
                    # connect NAT to inet and local switches
                    self.addLink(nat, interconnect, intfName1=inetIntf)
                    self.addLink(nat, switch, intfName1=localIntf, params1=natParams)
                    # add host and connect to local switch
                    host = self.addHost('%s_%d' % (node['name'], i),
                                        ip='192.168.%d.10%d/24' % (i, kk),
                                        defaultRoute='via %s' % localIP)
                    if 'link' in node:
                        loss = node['link']['loss']
                        latency = node['link']['latency']
                        bw = node['link']['bw']
                        self.addLink(host, switch, loss=loss, delay=latency, bw=bw)
                    else:
                        self.addLink(host, switch)


def portForward(net, id, dport):
    nat = net.get('nat%d' % id)
    h = net.get('h%d' % id)
    destIP = h.IP()
    dest = str(destIP) + ':' + str(dport)
    fport = dport
    intf = 'nat%d-eth0' % id
    nat.cmd( 'iptables -A PREROUTING', '-t nat -i', intf, '-p tcp --dport', fport, '-j DNAT --to', dest )
    nat.cmd( 'iptables -A FORWARD', '-p tcp', '-d', destIP, '--dport', dport, '-j ACCEPT' )