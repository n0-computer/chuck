# Netsim

## Requirements

- `ubuntu`
- `python3`
- `sudo apt install mininet`
- `sudo apt install openvswitch-testcontroller`
- `/var/lib/netsim`
- `dd if=/dev/urandom of=128MB.bin bs=64M count=2 iflag=fullblock`
- `dd if=/dev/urandom of=1GB.bin bs=64M count=16 iflag=fullblock`
- `iperf`

## Run

- `sudo python3 main.py sims/example.json`
- `./cleanup.sh`

## Notes

- `https://github.com/mininet/mininet/wiki/Introduction-to-Mininet`
- `sudo kill -9 $(pgrep ovs)`