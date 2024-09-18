import argparse
from sniffer.process import run_viz

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Input file path")
    parser.add_argument("--topo", help="Topo config file path")
    parser.add_argument("--keylog", help="NSS Keylog file path to decrypt TLS traffic")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()
    run_viz(args)
