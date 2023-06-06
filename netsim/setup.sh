sudo apt install mininet
sudo apt install openvswitch-testcontroller
sudo apt install iperf
# sudo apt install wireshark
sudo apt install tshark
sudo pip3 install pyshark
sudo pip3 install drawsvg
sudo pip3 install dpkt
mkdir -p logs
mkdir -p report
mkdir -p data
mkdir -p keys
mkdir -p bins
mkdir -p viz
cd data
rm -f 1G.bin
rm -f 100M.bin
for i in {1..10}; do
    cat ../../fixtures/10MiB.car >> 100M.bin
done
for i in {1..10}; do
    cat 100M.bin >> 1G.bin
done
cp ../../fixtures/key.pem ../bins/key.pem
cp ../../fixtures/cert.pem ../bins/cert.pem
cp ../../fixtures/derp.config.toml derp.config.toml
cp ../../fixtures/1MB.bin 1MB.bin
cp ../../fixtures/hello.bin hello.bin
