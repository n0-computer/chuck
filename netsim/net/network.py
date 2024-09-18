from mininet.topo import Topo
from mininet.nodelib import NAT
from mininet.node import Node


class StarTopo(Topo):
    """Single switch connected to n hosts.
    Default network layout:
            h0    h1
            \  /
            s1 - hN..."""

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
                        cls=NAT,
                        subnet=localSubnet,
                        inetIntf=inetIntf,
                        localIntf=localIntf,
                    )
                    switch = self.addSwitch(
                        "natsw%s%dr%d" % (node["name"][:2], i, runner_id)
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


def portForward(net, id, dport):
    nat = net.get("nat%d" % id)
    h = net.get("h%d" % id)
    destIP = h.IP()
    dest = str(destIP) + ":" + str(dport)
    fport = dport
    intf = "nat%d-eth0" % id
    nat.cmd(
        "iptables -A PREROUTING",
        "-t nat -i",
        intf,
        "-p tcp --dport",
        fport,
        "-j DNAT --to",
        dest,
    )
    nat.cmd(
        "iptables -A FORWARD", "-p tcp", "-d", destIP, "--dport", dport, "-j ACCEPT"
    )
