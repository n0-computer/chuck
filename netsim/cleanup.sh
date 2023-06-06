rm -rf logs/*
rm -rf report/*
rm -rf viz/*
sudo mn --clean
sudo kill -9 $(pgrep iroh)
sudo kill -9 $(pgrep derper)
sudo kill -9 $(pgrep ovs)