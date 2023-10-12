from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Lock
import logging
import sys

# Configure the logging system
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr
)

# Define the key-value store
store = {}
lock = Lock()

# Define the HTTP request handler
class KeyValueStoreHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock:
            try:
                # Get the key from the URL path
                key = self.path[1:]

                # Get the value from the store
                value = store.get(key)

                if value is None:
                    # Send a 404 response
                    self.send_response(404)
                    self.end_headers()
                    return

                # Send the value as JSON
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            except Exception as e:
                logging.error(f"unexpected error: {e}")

    def do_POST(self):
        with lock:
            try:
                # Get the key and value from the request body
                content_length = int(self.headers["Content-Length"])
                body = self.rfile.read(content_length)
                data = json.loads(body.decode())
                key = data["key"]
                value = data["value"]

                # Set the value in the store
                store[key] = value

                # Send a success response
                self.send_response(200)
                self.end_headers()
            except:
                try:
                    # Send a 500 response
                    self.send_response(500)
                    self.end_headers()
                except Exception as e:
                    logging.error(f"unexpected error: {e}")

    def do_PUT(self):
        with lock:
            try:
                # Get the key from the URL path
                key = self.path[1:]

                # Get the value from the store
                value = store.get(key)

                if value is None:
                    value = 0

                # Increment the value
                value += 1

                # Set the new value in the store
                store[key] = value

                # Send the new value as JSON
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            except:
                try:
                    # Send a 500 response
                    self.send_response(500)
                    self.end_headers()
                except Exception as e:
                    logging.error(f"unexpected error: {e}")

if __name__ == '__main__':
    # Define the HTTP server
    server_address = ("", 8000)
    httpd = HTTPServer(server_address, KeyValueStoreHandler)

    # Start the HTTP server
    logging.info("Starting HTTP server...")
    httpd.serve_forever()