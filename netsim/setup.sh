sudo apt install mininet
sudo apt install openvswitch-testcontroller
sudo apt install iperf
mkdir logs
mkdir report
mkdir -p /var/lib/netsim
sudo chmod -R 777 /var/lib/netsim
cd /var/lib/netsim
dd if=/dev/urandom of=128MB.bin bs=64M count=2 iflag=fullblock
dd if=/dev/urandom of=1GB.bin bs=64M count=16 iflag=fullblock