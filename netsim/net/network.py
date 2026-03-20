from mininet.topo import Topo
from mininet.nodelib import NAT
from mininet.node import Node


class EasyNAT(NAT):
    """NAT with endpoint-independent mapping (EIM / "easy" NAT).

    Standard MASQUERADE/SNAT creates address-dependent mappings where each
    destination gets a different external port (symmetric NAT). This breaks
    UDP hole punching because the peer's NAT mapping won't match.

    EasyNAT uses stateless 1:1 IP mapping via NETMAP, which always preserves
    the source port regardless of destination. This simulates consumer
    routers with endpoint-independent mapping (full-cone NAT) where UDP hole
    punching works.

    Since each private subnet has only one host, the 1:1 mapping is:
        private_host_ip:port <-> public_nat_ip:port (port always preserved)
    """

    def config(self, **params):
        """Configure NAT with endpoint-independent mapping via NETMAP."""
        if not self.localIntf:
            self.localIntf = self.defaultIntf()

        self.setManualConfig(self.localIntf)
        super(NAT, self).config(**params)

        if self.flush:
            self.cmd('sysctl net.ipv4.ip_forward=0')
            self.cmd('iptables -F')
            self.cmd('iptables -t nat -F')
            self.cmd('iptables -P INPUT ACCEPT')
            self.cmd('iptables -P OUTPUT ACCEPT')
            self.cmd('iptables -P FORWARD DROP')

        # Install forwarding rules
        self.cmd('iptables -I FORWARD',
                 '-i', self.localIntf, '-d', self.subnet, '-j DROP')
        self.cmd('iptables -A FORWARD',
                 '-i', self.localIntf, '-s', self.subnet, '-j ACCEPT')
        self.cmd('iptables -A FORWARD',
                 '-o', self.localIntf, '-d', self.subnet, '-j ACCEPT')

        # Determine public and private IPs
        inetIntf = [i for i in self.intfNames() if i != self.localIntf and i != 'lo']
        pubIP = None
        if inetIntf:
            pubIP = self.cmd('ip -4 addr show %s' % inetIntf[0] +
                             " | grep -oP '(?<=inet )\\S+'" +
                             " | cut -d/ -f1").strip()

        if pubIP:
            # Stateless 1:1 NAT using SNAT/DNAT with conntrack disabled for
            # endpoint-independent mapping. We use raw table NOTRACK to prevent
            # conntrack from creating per-destination entries, then use static
            # SNAT/DNAT for the IP translation.
            #
            # NOTRACK means conntrack won't interfere with port selection:
            # the source port is always preserved (1:1 mapping).
            self.cmd('iptables -t raw -A PREROUTING -j NOTRACK')
            self.cmd('iptables -t raw -A OUTPUT -j NOTRACK')

            # SNAT outbound: private -> public IP (port preserved due to NOTRACK)
            self.cmd('iptables -t nat -A POSTROUTING',
                     '-s', self.subnet, "'!'", '-d', self.subnet,
                     '-j SNAT --to-source', pubIP)

            # DNAT inbound: public -> private IP for any incoming traffic
            # This makes it a full-cone NAT: any external host can send to
            # public_ip:port and it gets forwarded to private_host:port.
            # Get the host IP (first host in subnet, e.g. 192.168.0.101)
            hostIP = self.cmd(
                "ip neigh show dev %s" % self.localIntf +
                " | head -1 | awk '{print $1}'"
            ).strip()
            if not hostIP:
                # Fallback: derive from subnet (e.g. 192.168.0.0/24 -> 192.168.0.101)
                import ipaddress
                net = ipaddress.ip_network(self.subnet, strict=False)
                # Hosts typically at .10X offset
                hostIP = str(list(net.hosts())[100]) if net.num_addresses > 101 else str(list(net.hosts())[-1])

            if hostIP:
                self.cmd('iptables -t nat -A PREROUTING',
                         '-d', pubIP,
                         '-j DNAT --to-destination', hostIP)
                # Also allow forwarding of incoming traffic to the host
                self.cmd('iptables -A FORWARD',
                         '-d', hostIP, '-j ACCEPT')
        else:
            self.cmd('iptables -t nat -A POSTROUTING',
                     '-s', self.subnet, "'!'", '-d', self.subnet,
                     '-j MASQUERADE')

        self.cmd('sysctl net.ipv4.ip_forward=1')

    def terminate(self):
        """Stop NAT/forwarding."""
        self.cmd('iptables -F')
        self.cmd('iptables -t nat -F')
        self.cmd('iptables -t raw -F')
        self.cmd('sysctl net.ipv4.ip_forward=%s' % self.forwardState)
        Node.terminate(self)


class StarTopo(Topo):
    """Single switch connected to n hosts.

    Default network layout:
            h0   h1
            |  /
            s1 - hN...
    """

    def build(
        self,
        nodes=[
            {"name": "hx", "count": 1, "type": "public"},
            {"name": "h", "count": 1, "type": "public"},
        ],
        runner_id=0,
        interconnect="s1",
    ):

        self.runner_id = runner_id
        routerName = "r0_" + str(runner_id)
        defaultIP = "10.0.0.1/8"  # IP address for r0-eth1
        router = self.addNode(routerName, cls=LinuxRouter, ip="10.1.1.1")
        interconnect = self.addSwitch(interconnect + "-r" + str(runner_id))

        self.addLink(
            interconnect,
            router,
            intfName2=routerName + "-eth1",
            params2={"ip": defaultIP},
        )

        kk = 0
        for node in nodes:
            if node["type"] == "public":
                for i in range(int(node["count"])):
                    h = self.addHost(
                        "%s_%d_r%d" % (node["name"], i, runner_id),
                        cls=EdgeNode,
                        defaultRoute="via 10.1.1.1",
                    )
                    if "link" in node:
                        loss = node["link"]["loss"]
                        latency = node["link"]["latency"]
                        bw = node["link"]["bw"]
                        self.addLink(interconnect, h, loss=loss, delay=latency, bw=bw)
                    else:
                        self.addLink(interconnect, h)

            if node["type"] == "nat":
                kk += 1
                for i in range(int(node["count"])):
                    inetIntf = "n_%s%dr%d-e0" % (node["name"], i, runner_id)
                    localIntf = "n_%s%dr%d-e1" % (node["name"], i, runner_id)
                    localIP = "192.168.%d.1" % i
                    localSubnet = "192.168.%d.0/24" % i
                    natParams = {"ip": "%s/24" % localIP}
                    # add NAT to topology
                    nat = self.addNode(
                        "n_%s%dr%d" % (node["name"], i, runner_id),
                        cls=EasyNAT,
                        subnet=localSubnet,
                        inetIntf=inetIntf,
                        localIntf=localIntf,
                    )
                    switch = self.addSwitch(
                        "ns%s%dr%d" % (node["name"], i, runner_id)
                    )
                    # connect NAT to inet and local switches
                    self.addLink(nat, interconnect, intfName1=inetIntf)
                    self.addLink(nat, switch, intfName1=localIntf, params1=natParams)
                    # add host and connect to local switch
                    host = self.addHost(
                        "%s_%d_r%d" % (node["name"], i, runner_id),
                        ip="192.168.%d.10%d/24" % (i, kk),
                        defaultRoute="via %s" % localIP,
                    )
                    if "link" in node:
                        loss = node["link"]["loss"]
                        latency = node["link"]["latency"]
                        bw = node["link"]["bw"]
                        self.addLink(host, switch, loss=loss, delay=latency, bw=bw)
                    else:
                        self.addLink(host, switch)

            if node["type"] == "multi_nat":
                kk += 1
                for i in range(int(node["count"])):
                    # NAT subnet indices - use high numbers to avoid collision
                    nat1_subnet_idx = 100 + i * 2
                    nat2_subnet_idx = 100 + i * 2 + 1

                    # First NAT
                    nat1_inetIntf = "n1_%s%dr%d-e0" % (node["name"], i, runner_id)
                    nat1_localIntf = "n1_%s%dr%d-e1" % (node["name"], i, runner_id)
                    nat1_localIP = "192.168.%d.1" % nat1_subnet_idx
                    nat1_localSubnet = "192.168.%d.0/24" % nat1_subnet_idx
                    nat1 = self.addNode(
                        "n1_%s%dr%d" % (node["name"], i, runner_id),
                        cls=EasyNAT,
                        subnet=nat1_localSubnet,
                        inetIntf=nat1_inetIntf,
                        localIntf=nat1_localIntf,
                    )
                    switch1 = self.addSwitch("ns1%s%dr%d" % (node["name"], i, runner_id))
                    self.addLink(nat1, interconnect, intfName1=nat1_inetIntf)
                    self.addLink(
                        nat1, switch1,
                        intfName1=nat1_localIntf,
                        params1={"ip": "%s/24" % nat1_localIP},
                    )

                    # Second NAT
                    nat2_inetIntf = "n2_%s%dr%d-e0" % (node["name"], i, runner_id)
                    nat2_localIntf = "n2_%s%dr%d-e1" % (node["name"], i, runner_id)
                    nat2_localIP = "192.168.%d.1" % nat2_subnet_idx
                    nat2_localSubnet = "192.168.%d.0/24" % nat2_subnet_idx
                    nat2 = self.addNode(
                        "n2_%s%dr%d" % (node["name"], i, runner_id),
                        cls=EasyNAT,
                        subnet=nat2_localSubnet,
                        inetIntf=nat2_inetIntf,
                        localIntf=nat2_localIntf,
                    )
                    switch2 = self.addSwitch("ns2%s%dr%d" % (node["name"], i, runner_id))
                    self.addLink(nat2, interconnect, intfName1=nat2_inetIntf)
                    self.addLink(
                        nat2, switch2,
                        intfName1=nat2_localIntf,
                        params1={"ip": "%s/24" % nat2_localIP},
                    )

                    # Host with two interfaces - initially routed via NAT1
                    host_ip1 = "192.168.%d.10/24" % nat1_subnet_idx
                    host_ip2 = "192.168.%d.10/24" % nat2_subnet_idx
                    host = self.addHost(
                        "%s_%d_r%d" % (node["name"], i, runner_id),
                        ip=host_ip1,
                        defaultRoute="via %s" % nat1_localIP,
                    )

                    # Connect host to both NAT switches
                    if "link" in node:
                        loss = node["link"]["loss"]
                        latency = node["link"]["latency"]
                        bw = node["link"]["bw"]
                        self.addLink(host, switch1, loss=loss, delay=latency, bw=bw)
                        self.addLink(host, switch2, loss=loss, delay=latency, bw=bw)
                    else:
                        self.addLink(host, switch1)
                        self.addLink(host, switch2)

        box = self.addHost(
            "zbox1-r" + str(runner_id),
            cls=EdgeNode,
            ip="10.1.1.2",
            defaultRoute="via 10.1.1.1",
        )  # creates a dedicated node to play around
        self.addLink(interconnect, box)


"A Node with multicast stuff."


class EdgeNode(Node):
    def config(self, **params):
        super(EdgeNode, self).config(**params)
        intfName = self.intfNames()[0]
        self.cmd("sysctl net.ipv4.icmp_echo_ignore_broadcasts=0")
        self.cmd("route add -net 224.0.0.0 netmask 240.0.0.0 dev " + intfName)
        self.cmd("smcrouted -l debug -I smcroute-" + self.name)
        self.cmd("sleep 1")
        self.cmd(
            "smcroutectl -I smcroute-" + self.name + " join " + intfName + " 239.0.0.1"
        )

    def terminate(self):
        self.cmd("smcroutectl -I smcroute-" + self.name + " kill")
        super(EdgeNode, self).terminate()


"A Node with IP forwarding enabled."


class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        # Enable forwarding on the router
        self.cmd("sysctl net.ipv4.ip_forward=1")
        self.cmd("sysctl net.ipv4.icmp_echo_ignore_broadcasts=0")
        self.cmd("sysctl net.ipv4.conf." + self.name + "-eth1.force_igmp_version=2")
        self.cmd("smcrouted -l debug -I smcroute-" + self.name)
        self.cmd("sleep 1")
        self.cmd(
            "smcroutectl -I smcroute-"
            + self.name
            + " add "
            + self.name
            + "-eth1 239.0.0.1 "
            + self.name
            + "-eth2 "
            + self.name
            + "-eth3"
        )

    def terminate(self):
        self.cmd("sysctl net.ipv4.ip_forward=0")
        self.cmd("smcroutectl -I smcroute-" + self.name + " kill")
        super(LinuxRouter, self).terminate()
