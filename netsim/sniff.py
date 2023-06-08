import socket
import sys
import threading
import dpkt
from struct import unpack
from ipaddress import ip_address

HOST_TYPES = ['Host', 'CPULimitedHost', 'NAT']
SWITCH_TYPES = ['UserSwitch', 'OVSSwitch', 'OVSBridge', 'OVSSwitch', 'IVSSwitch', 'LinuxBridge', 'OVSSwitch']
CONTROLLER_TYPES = ['Controller', 'OVSController', 'NOX', 'RemoteController', 'Ryu', 'DefaultController', 'NullController']

def parse_ips(packet):
    eth_length = 14
    eth_header = packet[:eth_length]
    eth = unpack('!6s6sH', eth_header)
    eth_protocol = socket.ntohs(eth[2])
    if eth_protocol == 8:
        ip_header = packet[eth_length:20 + eth_length]
        iph = unpack('!BBHHHBBH4s4s', ip_header)
        s_addr = socket.inet_ntoa(iph[8]);
        d_addr = socket.inet_ntoa(iph[9]);
        return s_addr, d_addr
    return None, None

class Sniffer():

    def __init__(self, net, output="netsim.pcap"):
        self.output=output

        self.net = net
        self.nodes = []
        self.node_ips = set()
        self.interfaces = []

        self.snifferd = None

        self.TopoInfo()

    def start(self):
        self.output_f = open(self.output, 'wb')
        self.output_f_viz = open(self.output.replace('.pcap', '.viz.pcap'), 'wb')
        self.kill = False
        #Start siniffing packets on Mininet interfaces
        self.snifferd = threading.Thread( target=self.sniff )
        self.snifferd.daemon = True
        self.snifferd.start()

    def get_topoinfo(self):
        return {
            'nodes': self.nodes,
            'interfaces': self.interfaces
        }

    def TopoInfo(self):
        for item , value in self.net.items():
            node = {'name': item, 'type':value.__class__.__name__}
            if node['type'] in CONTROLLER_TYPES:
                node['ip'] = value.ip
                node['port'] = value.port
            elif node['type'] in SWITCH_TYPES:
                node['dpid'] = value.dpid
            elif node['type'] in HOST_TYPES:
                node['ip'] = value.IP()
            self.nodes.append(node)

            for intf in value.intfList():
                t_intf = str(intf.link).replace(intf.name,'').replace('<->','')
                if t_intf != 'None':
                    self.interfaces.append(
                        {
                            'node': node['name'], 
                            'type': node['type'],
                            'interface': intf.name,
                            'mac': intf.mac,
                            'ip':intf.ip,
                            'link': t_intf
                        })
                    self.node_ips.add(intf.ip)
        
    def intfExists(self, interface, by_mac=False):
        for intf in self.interfaces:
            if by_mac:
                if intf['mac'] == interface:
                    return intf
            elif intf["interface"] == interface:
                return intf
        return None
    
    def nodeExists(self, node):
        for n in self.nodes:
            if n['name'] == node:
                return n
        return None
    
    def pkt_src_dest_rewrite(self, pkt, sip, smisnode, dip, dmisnode):
        # if smi ip != sip then rewrite sip
        # if dmi ip != dip then rewrite dip
        # if src ip or dst ip not known then ignore
        if not sip in self.node_ips:
            return pkt
        if not dip in self.node_ips:
            return pkt
        epkt = dpkt.ethernet.Ethernet(pkt)
        if sip != smisnode['ip']:
            ip = epkt.data
            tip = ip_address(smisnode['ip']).packed
            ip.src = tip
        if dip != dmisnode['ip']:
            ip = epkt.data
            tip = ip_address(dmisnode['ip']).packed
            ip.dst = tip
        return epkt
    
    def sniff(self):
        print("Starting sniffer")
        try:
            s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
        except socket.error as msg:
            print('Error creating socket:' + str(msg[0]) + ' | ' + msg[1])
            sys.exit()
        pcapw=dpkt.pcap.Writer(self.output_f)
        pcapw_viz=dpkt.pcap.Writer(self.output_f_viz)
        while True:
            if self.kill:
                break
            packet = s.recvfrom(65565)

            try:
                interface = packet[1][0]
                intf = self.intfExists(interface)
                if not intf:
                    continue
            except Exception as e:
                continue
            
            direction = "incoming"
            if packet[1][2] == socket.PACKET_OUTGOING:
                direction = "outgoing"

            packet = packet[0]

            dstMAC = ':'.join('%02x' % b for b in packet[0:6])
            srcMAC = ':'.join('%02x' % b for b in packet[6:12])

            srcMAC = str(srcMAC)
            dstMAC = str(dstMAC)

            smi = self.intfExists(srcMAC, True)
            dmi = self.intfExists(dstMAC, True)

            if not smi:
                print("smi not found", srcMAC)
            
            if not dmi:
                # print("dmi not found", dstMAC)
                continue

            sip, dip = parse_ips(packet)

            link = self.intfExists(intf["link"])
            src, dst = intf["node"], intf["link"].split('-')[0]
            if direction == "incoming":
                src, dst = intf["link"].split('-')[0], intf["node"]

            src_node = self.nodeExists(src)

            smisnode = self.nodeExists(smi['node'])
            dmisnode = self.nodeExists(dmi['node'])

        
            if not src_node['type'] in SWITCH_TYPES:
                pcapw.writepkt(packet)
                wpkt = self.pkt_src_dest_rewrite(packet, sip, smisnode, dip, dmisnode)
                pcapw_viz.writepkt(wpkt)

    def close(self):
        if self.snifferd:
            self.kill = True
        try:
            self.output_f.close()
        except Exception:
            pass