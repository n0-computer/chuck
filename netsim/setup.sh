sudo apt install mininet
sudo apt install openvswitch-testcontroller
sudo apt install iperf
mkdir -p logs
mkdir -p report
mkdir -p data
mkdir -p keys
mkdir -p bins
cd data
rm -f 1G.bin
rm -f 100M.bin
for i in {1..10}; do
    cat ../../fixtures/10MiB.car >> 100M.bin
done
for i in {1..10}; do
    cat 100M.bin >> 1G.bin
done