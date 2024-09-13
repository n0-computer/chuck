# Netsim

## Requirements
- `sudo ./setup.sh`
- Linux machine, tested on ubuntu 20.04 & 22.04

### Warning:
- Requires root access
- Dirties your system python dependencies 

## Locally

You can also do this locally on a linux machine.  With a few modifications you don’t even need to do much as root:

- clone [**iroh**](https://github.com/n0-computer/iroh) and [**chuck**](https://github.com/n0-computer/chuck) into the same directory.
- Check `chuck/netsim/scripts/ubuntu_deps.sh`to find what the system dependencies are
- `cd chuck/netsim`
- Create a virtual environment:
    - `python -m venv .venv`
    - `source .venv/bin/activate`
    - `./scripts/python_deps.sh`
- Run `./scripts/project_deps` to configure the project structure and generate fixtures
- Continue with in the iroh repo, build iroh and copy it into chuck/netsim/bins. I found building in release mode to be sufficient, not release-optimized like what CI does. `cargo build --release && cp ./target/release/iroh ../chuck/netsim/bins/`
    - Do not run kill, these are services managed by systemd
    - Run [`main.py`](http://main.py) as root, using the python from your virtualenv:
        - `./venv/bin/python main.py --integrations sims/mini`

## Run

- `sudo python3 main.py sims/example.json`
- `./cleanup.sh`

## Notes

- `https://github.com/mininet/mininet/wiki/Introduction-to-Mininet`
- `sudo kill -9 $(pgrep ovs)` - when stuck with weird errors due to the process failing mid way on a simulation