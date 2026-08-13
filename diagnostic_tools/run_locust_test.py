import subprocess
import time
import requests

# We will run a quick locust test for 5 seconds with 10 users to see what exactly happens.
print("Starting Locust test...")
proc = subprocess.Popen(
    ["uv", "run", "locust", "-f", "locustfile_surge.py", "--headless", "-u", "10", "-r", "2", "-t", "10s", "--host", "http://127.0.0.1:8000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

stdout, stderr = proc.communicate()
print("Locust STDOUT:")
print(stdout)
print("Locust STDERR:")
print(stderr)
