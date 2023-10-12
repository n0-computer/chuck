import os
import playbook_client as pbc
import iroh
import time
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

if IROH_DATA_DIR is None:
    logging.info("IROH_DATA_DIR is not set")
    exit(1)

node = iroh.IrohNode(IROH_DATA_DIR)
logging.info("Started Iroh node: {}".format(node.node_id()))

syncer.set("srv_node_id", node.node_id())

author = node.author_new()
logging.info("Created author: {}".format(author.to_string()))

ticket = syncer.wait_for("ticket")

doc_ticket = iroh.DocTicket.from_string(ticket)
doc = node.doc_join(doc_ticket)
logging.info("Joined doc: {}".format(doc.id()))

syncer.set("get_ready", 1)

time.sleep(15)

keys = doc.keys()
logging.info("Keys:")
for key in keys:
    content = doc.get_content_bytes(key)
    logging.info("{} : {} (hash: {})".format(key.key(), content.decode("utf8"), key.hash().to_string()))

logging.info("Done logging.infoing keys...")

syncer.inc("test_done")
time.sleep(5)
syncer.inc("test_done")

logging.info("Done")