import requests
import json
import time
import logging

# The playbook_engine should always be the first node to spawn
default_url = "http://10.0.0.1:8000"

class Syncer:
    def __init__(self, addr=default_url, run_id="", tick_interval = 0.5, timeout=60):
        self.addr = addr
        self.run_id = run_id
        self.tick_interval = tick_interval
        self.timeout = timeout

    def set(self, key, value):
        key = f"{self.run_id}_{key}"
        data = {"key": key, "value": value}
        response = requests.post(self.addr, data=json.dumps(data), headers={"Content-Type": "application/json"})
        if response.status_code != 200:
            logging.info("Error setting value:", response.text)
    
    def inc(self, key):
        key = f"{self.run_id}_{key}"
        response = requests.put(f"{self.addr}/{key}")
        if response.status_code != 200:
            logging.info("Error incrementing value:", response.text)
    
    def wait_for(self, key):
        key = f"{self.run_id}_{key}"
        start = time.time()
        while True:
            logging.info("wating 1...")
            if time.time() - start > self.timeout:
                raise Exception(f"Timeout waiting for {key}")
            response = requests.get(f"{self.addr}/{key}")
            if response.status_code == 200:
                value = json.loads(response.text)
                return value
            time.sleep(self.tick_interval)
        
    def wait_for_val(self, key, val):
        key = f"{self.run_id}_{key}"
        start = time.time()
        while True:
            logging.info("wating 2...")
            if time.time() - start > self.timeout:
                raise Exception(f"Timeout waiting for {key} to be {val}")
            response = requests.get(f"{self.addr}/{key}")
            if response.status_code == 200:
                value = json.loads(response.text)
                if value == val:
                    return value
            time.sleep(self.tick_interval)