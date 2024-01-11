import os
import playbook_client as pbc
import iroh
import argparse
import logging
import sys

iroh.set_log_level(iroh.LogLevel.DEBUG)

# Configure the logging system
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr
)

parser = argparse.ArgumentParser(description="Test param handler")
parser.add_argument("--syncer", help="Syncer address")
args = parser.parse_args()

# syncer = pbc.Syncer(addr="http://127.0.0.1:8000")
syncer = pbc.Syncer(addr=f"http://{args.syncer}:8000")

IROH_DATA_DIR = os.environ.get("IROH_DATA_DIR")
logging.info("IROH_DATA_DIR: {}".format(IROH_DATA_DIR))

if IROH_DATA_DIR is None:
    logging.info("IROH_DATA_DIR is not set")
    exit(1)

logging.info("Starting Iroh node...")

node = iroh.IrohNode(IROH_DATA_DIR)
logging.info("Started Iroh node: {}".format(node.node_id()))

syncer.set("srv_node_id", node.node_id())

author = node.author_new()
logging.info("Created author: {}".format(author.to_string()))

doc = node.doc_new()
logging.info("Created doc: {}".format(doc.id()))

ticket = doc.share_write()
logging.info("Write-Access Ticket: {}".format(ticket.to_string()))

syncer.set("ticket", ticket.to_string())

syncer.wait_for("get_ready")
logging.info("Ready!")

hash = doc.set_bytes(author, bytes("foo", "utf8"), bytes("bar", "utf8"))
logging.info("Inserted: {}".format(hash.to_string()))

syncer.wait_for_val("test_done", "2")

logging.info("Done")