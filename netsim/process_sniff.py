import argparse
import pyshark
import sys
import drawsvg as draw
import math
import json

def read_topo(path):
    if path:
        f = open(path)
        d = json.load(f)
        f.close()
        return d
    return None

def load_pcap(path, keylog=None, topo_path=None):
    parameters_dict = {}
    if keylog:
        parameters_dict = {'-o' : "ssl.keylog_file:" + keylog}
    cap_json = pyshark.FileCapture(path, custom_parameters=parameters_dict)
    packets = []
    str_packet_data = []

    topo = read_topo(topo_path)
    topo_nodes = []
    topo_node_ip_map = {}
    if topo:
        i=0
        for node in topo['nodes']:
            if node['type'] == 'Host' or node['type'] == 'NAT':
                topo_nodes.append(node)
                topo_node_ip_map[node['ip']] = i
                i+=1

    node_list = []
    ip_set = set()

    for packet in cap_json:
        if len(packet.layers) == 2:
            if 'arp' in packet: # ignore ARP
                continue
        if 'ip' in packet:
            ip_set.add(packet.ip.src)
            ip_set.add(packet.ip.dst)
            p = {
                'src': packet.ip.src,
                'dst': packet.ip.dst,
                'type': '',
                'ipv6': False
            }           

            if 'tcp' in packet:
                p['type'] = 'TCP'
            elif 'udp' in packet:
                p['type'] = 'UDP'

            if 'quic' in packet:
                p['type'] = 'QUIC'
            elif 'http' in packet:
                p['type'] = 'HTTP'
            elif 'stun' in packet:
                p['type'] = 'STUN'
            elif 'icmp' in packet:
                p['type'] = 'ICMP'
            
            packets.append(p)
            zk = packet.__str__().replace('\n', '<\\n>')
            str_packet_data.append(zk)

        if 'ipv6' in packet:
            p = {
                'src': packet.ipv6.src,
                'dst': packet.ipv6.dst,
                'type': 'ICMPv6',
                'ipv6': True
            }

    js_packet_data = "const pkt_data = ["
    for i in range(len(str_packet_data)):
        js_packet_data += '`{}`,'.format(str_packet_data[i])
    js_packet_data += "];"

    for ip in ip_set:
        n = {
            'type': 'node',
            'id': ip,
            'ip': ip
        }
        if ip in topo_node_ip_map:
            tn = topo_nodes[topo_node_ip_map[ip]]
            if tn['name'].startswith('iroh-relay'):
                n['type'] = 'relay'
                n['id'] = tn['name']
            if tn['name'].startswith('iroh'):
                n['type'] = 'iroh'
                n['id'] = tn['name'].replace('iroh_', '')
            elif tn['name'].startswith('n_'):
                n['type'] = 'nat'
                n['id'] = tn['name']
            
        node_list.append(n)
    return packets, js_packet_data, node_list

class NetsimViz():

    HOVER_JS = """
    function pktAnalysisOnLoad(event) {
        console.log('pktAnalysisOnLoad');
        var pkts = document.getElementsByClassName('pkt');
        for (var i = 0; i < pkts.length; i++) {
            pkts[i].addEventListener('mouseover', pktMouseOverEvt);
        }
        var up = document.getElementById('up_ttx');
        var down = document.getElementById('down_ttx');
        up.addEventListener('click', upTTX);
        down.addEventListener('click', downTTX);
    }
    function pktMouseOverEvt(event) {
        var target = event.target;
        var label = target.getAttribute('data-label');
        var id = target.getAttribute('data-id');
        console.log(label);
        console.log(id);
        renderTTX(id, 0);
    }
    function upTTX(event) {
        var ttx = document.getElementById('ttx');
        var id = parseInt(ttx.getAttribute('data-pid'), 10);
        var offset = parseInt(ttx.getAttribute('data-offset'), 10);
        var len = parseInt(ttx.getAttribute('data-len'), 10);
        if (offset > 0) {
            offset -= 5;
        }
        if (offset < 0) {
            offset = 0;
        }
        renderTTX(id, offset);
    }
    function downTTX(event) {
        var ttx = document.getElementById('ttx');
        var id = parseInt(ttx.getAttribute('data-pid'), 10);
        var offset = parseInt(ttx.getAttribute('data-offset'), 10);
        var len = parseInt(ttx.getAttribute('data-len'), 10);
        if (offset < len - 48) {
            offset += 5;
        }
        renderTTX(id, offset);
    }
    function renderTTX(id, offset) {
        var ttx = document.getElementById('ttx');
        ttx.setAttribute('data-pid', id);
        ttx.setAttribute('data-offset', offset);
        var x_pos = ttx.getAttribute('x');
        var lines = pkt_data[id].split("<\\n>");
        console.log('LL', lines.length);
        ttx.setAttribute('data-len', lines.length);
        var up = document.getElementById('up_ttx');
        var down = document.getElementById('down_ttx');
        if (offset > 0) {
            console.log('show up');
            up.setAttribute('visibility', 'visible');
        } else {
            up.setAttribute('visibility', 'hidden');
        }
        if (lines.length - offset > 48) {
            console.log('show down');
            down.setAttribute('visibility', 'visible');
        } else {
            down.setAttribute('visibility', 'hidden');
        }
        var ih = '';
        for (var i = offset; i < lines.length && i < 48 + offset; i++) {
            ih += '<tspan x="' + x_pos + '" dy="1em" xml:space="preserve">' + lines[i].replace('\\t', '     ') + '</tspan>';
        }
        ttx.innerHTML = ih;
    }
    """

    def __init__(self):
        # TODO make configurable
        self.size_x = 1600
        self.size_y = 800
        self.offset_x = 160
        self.batch_time = 1.25
        self.batch_interval = 1
        self.duration = 0
        self.node_size = 60
        self.R = 300
        self.show_node_labels = True
        self.pkt_size = 12

        self.node_color_map = {
            'iroh': '#7c7cff',
            'relay': '#ff7c7c',
            'node': '#7cff7c',
            'nat': '#ff7cff',
        }

        self.pkt_color_map = {
            'ICMP': '#8ecae6',
            'ICMPv6': '#219EBC',
            'TCP': '#2a9d8f',
            'UDP': '#ffd60a',
            'STUN': '#035781',
            'HTTP': '#FB8500',
            'QUIC': '#e63946',
        }

    def run(self, args):
        packets, js_packet_data, node_list = load_pcap(args['path'], args['keylog'], args['topo'])

        self.duration = self.batch_time + self.batch_interval * len(packets) + 1

        self.d = draw.Drawing(self.size_x, self.size_y, origin='center',
            animation_config=draw.types.SyncedAnimationConfig(
                self.duration,  
                show_playback_progress=True,
                show_playback_controls=True))
        
        self.d.append_javascript(self.HOVER_JS, onload="pktAnalysisOnLoad(event)")
        self.d.append_javascript(js_packet_data)

        self.draw_background()
        self.draw_legend(-self.size_x/2 + 50, -self.size_y/2 + 120)
        self.draw_title('relay__1_to_1', 0, -self.size_y/2 + 50) # TODO correct title
        self.draw_ttx()

        nodes = []
        self.node_ip_map = {}

        i = 0
        for node in node_list:
            n = {
                'type': node['type'],
                'id': node['id'],
                'draw': self.draw_node(0, 0, node)
            }
            nodes.append(n)
            self.node_ip_map[node['ip']] = i
            i+=1

        i = 0
        for node in nodes:
            x, y = self.calculate_node_position(self.R, len(nodes), i)
            node['pos'] = [x, y]
            self.animate_node_to(node['draw'], x, y, 1)
            i+=1

        for node in nodes:
            self.attach(node['draw'])

        self.play(packets, nodes)
        
    def play(self, packets, nodes):
        pkts = []

        i = 0
        for pp in packets:
            pkts.append(self.send_pkt(nodes[self.node_ip_map[pp['src']]], nodes[self.node_ip_map[pp['dst']]], pp, self.batch_time, self.batch_interval, i))
            self.batch_time += self.batch_interval
            i+=1

        for pkt in pkts:
            self.attach(pkt)

    def export(self, path):
        self.d.save_svg(path)

    def attach(self, items):
        for k in items:
            self.d.append(k)

    def draw_background(self):
        bg = draw.Rectangle(-self.size_x/2, -self.size_y/2, self.size_x, self.size_y, fill='#eee')
        self.d.append(bg)

    def draw_ttx(self):
        ttx_title = draw.Text('Console', 14, self.size_x/2-605, -self.size_y/2+60, fontWeight='bold', center=True, fill='#666', font_family='Helvetica', text_anchor='left')
        ttx = draw.Text([], 12, self.size_x/2-600, -self.size_y/2+90, center=True, fill='#666', font_family='Helvetica', id='ttx', text_anchor='left')
        box = draw.Rectangle(self.size_x/2-610, -self.size_y/2+76, 580, self.size_y-180, fill='#ddd', rx='4', ry='4')

        ox = self.size_x/2 - 515
        oy = -self.size_y/2+66
        up = draw.Lines(ox, oy, 10 + ox, oy - 15, 20 + ox, oy, fill='#bbb', close='true', id='up_ttx', visibility='hidden')

        ox = self.size_x/2 - 540
        oy = -self.size_y/2+52
        down = draw.Lines(ox, oy, 10 + ox, oy + 15, 20 + ox, oy, fill='#bbb', close='true', id='down_ttx', visibility='hidden')
        self.attach([box, ttx_title, ttx, up, down])
        return [box, ttx_title, up, down, ttx]

    def draw_legend(self, x, y):
        res = []
        legend_title = draw.Text('Legend', 16, x, y, font_weight='bold', center=True, fill='#666', font_family='Helvetica')
        res.append(legend_title)
        i = 1
        for k in self.pkt_color_map:
            circle = draw.Circle(x-12, y+i*40, self.pkt_size, fill=self.pkt_color_map[k], stroke=None, stroke_width=0)
            label = draw.Text(k, 12, x+8, y+i*40+4, fill='#666', font_family='Helvetica')
            res.append(circle)
            res.append(label)
            i+=1

        i+=0.5
        circle = draw.Circle(x-12, y+i*40, self.pkt_size, fill='#0000', stroke='#d2a', stroke_width=2)
        label = draw.Text('IPv6', 12, x+8, y+i*40+4, fill='#666', font_family='Helvetica')
        res.append(circle)
        res.append(label)
        i+=1
        circle = draw.Circle(x-12, y+i*40, self.pkt_size, fill='#0000', stroke='#84a59d', stroke_width=2)
        label = draw.Text('IPv4', 12, x+8, y+i*40+4, fill='#666', font_family='Helvetica')
        res.append(circle)
        res.append(label)
        self.attach(res)
        return res
    
    def draw_title(self, c, x, y):
        title = draw.Text(c, 24, x-2*self.offset_x, y, font_weight='bold', center=True, fill='#666', font_family='Helvetica')
        self.d.append(title)
        return title

    def draw_node(self, x, y, node):
        res = []
        box = draw.Rectangle(x-self.node_size/2-self.offset_x, y-self.node_size/2, self.node_size, self.node_size, fill=self.node_color_map[node['type']], rx='4', ry='4')
        box_name = draw.Text(node['type'], 16, x-self.offset_x, y+10, center=True, fill='#fff', font_family='Helvetica')
        res.append(box)
        res.append(box_name)
        if self.show_node_labels:
            label = draw.Text(node['id'], 14, x-self.offset_x, y+40, center=True, fill='#666', font_family='Helvetica')
            res.append(label)
            ipls = ''
            if node['id'] != node['ip']:
                ipls = node['ip']
            ip_label = draw.Text(ipls, 14, x-self.offset_x, y+60, center=True, fill='#666', font_family='Helvetica')
            res.append(ip_label)
        self.animate_node_to(res, x, y, 0)
        self.animate_node_to(res, x, y, 0.5)
        return res

    def draw_pkt(self, x, y, pkt, t, id):
        res = []
        stroke = None
        if pkt['ipv6']:
            stroke = '#d2a'
        else:
            stroke = '#84a59d'
        circle = draw.Circle(x-self.offset_x, y, 0, fill=self.pkt_color_map[pkt['type']], stroke=stroke, stroke_width=2, class_='pkt', data_label=pkt['type'], data_id=id)
        res.append(circle)
        self.animate_pkt_to(res, x, y, 0, t)
        return res

    def animate_node_to(self, node, x, y, t):
        node[0].add_key_frame(t, x=x-self.node_size/2-self.offset_x, y=y-self.node_size/2)
        node[1].add_key_frame(t, x=x-self.offset_x, y=y+10)
        i = 2
        if self.show_node_labels:
            node[i].add_key_frame(t, x=x-self.offset_x, y=y+40)
            node[i+1].add_key_frame(t, x=x-self.offset_x, y=y+60)
            i+=2

    def animate_pkt_to(self, pkt, x, y, r, t):
        pkt[0].add_key_frame(t, cx=x-self.offset_x, cy=y, r=r)

    def show_pkt(self, pkt, t):
        pkt[0].add_key_frame(t+self.batch_interval/10, r=self.pkt_size)

    def hide_pkt(self, pkt, t):
        pkt[0].add_key_frame(t, r=0)

    def send_pkt(self, n_from, n_to, pkt, t, i, pkt_id):
        p_from = n_from['pos']
        p_to = n_to['pos']
        p = self.draw_pkt(p_from[0], p_from[1], pkt, t, pkt_id)
        self.show_pkt(p, t)
        self.animate_pkt_to(p, p_to[0], p_to[1], self.pkt_size, t+i)
        self.hide_pkt(p, t+i)
        return p

    def calculate_node_position(self, r, node_cnt, i):
        x = r*math.cos(i*2*math.pi/node_cnt)-self.offset_x
        y = r*math.sin(i*2*math.pi/node_cnt)
        return (x, y)
    
def run_viz(args):
    t_stdout = sys.stdout
    class PseudoNonTTY(object):
        def __init__(self, underlying):
            self.__underlying = underlying
        def __getattr__(self, name):
            return getattr(self.__underlying, name)
        def isatty(self):
            return False
    
    sys.stdout = PseudoNonTTY(sys.stdout) # disable color output on packet data for JS
    
    viz = NetsimViz()
    viz.run(args)
    viz.export(args['output'])

    sys.stdout = t_stdout

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help = "Input file path")
    parser.add_argument("--topo", help = "Topo config file path")
    parser.add_argument("--keylog", help = "NSS Keylog file path to decrypt TLS traffic")
    parser.add_argument("--output", help = "Output file path")
    args = parser.parse_args()
    run_viz(args)