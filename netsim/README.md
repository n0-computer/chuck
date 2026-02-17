# Netsim

## Requirements
- Linux machine (tested on Ubuntu 20.04 & 22.04)
- Root access (`sudo`)
- [uv](https://docs.astral.sh/uv/) for Python dependency management

## Quick Setup

```bash
sudo ./setup.sh
```

This runs the install scripts in `scripts/` which handle system packages, Python
dependencies (via `uv`), and project fixtures.

## Local Setup

For development on a local Linux machine without dirtying system Python:

1. Clone [iroh](https://github.com/n0-computer/iroh) and [chuck](https://github.com/n0-computer/chuck) into the same directory.
2. Install system dependencies listed in `scripts/ubuntu_deps.sh`.
3. Set up Python deps:
   ```bash
   cd chuck/netsim
   uv venv
   source .venv/bin/activate
   uv pip install -r scripts/requirements.txt
   ```
4. Configure project structure and generate fixtures:
   ```bash
   ./scripts/project_deps.sh
   ```
5. Build iroh and copy binaries:
   ```bash
   cd ../iroh
   cargo build --release
   cp target/release/iroh ../chuck/netsim/bins/
   ```
6. Run simulations (use the venv Python as root):
   ```bash
   sudo .venv/bin/python main.py --integration sims/mini
   ```

## Run

```bash
sudo python3 main.py sims/example.json
./cleanup.sh
```

## Notes

- Mininet docs: https://github.com/mininet/mininet/wiki/Introduction-to-Mininet
- If stuck with errors from a failed simulation: `sudo kill -9 $(pgrep ovs)`
