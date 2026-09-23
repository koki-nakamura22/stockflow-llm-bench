import os
import socket
import threading
import time

import uvicorn
from stockflow.main import app

# Set BASE_URL to localhost for tests
os.environ.setdefault("BASE_URL", "http://localhost:8000")

# Create a log file to confirm conftest execution
with open("conftest.log", "w") as f:
    f.write("conftest executed\n")

# Start the FastAPI app in a background thread before tests

def _run_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

server_thread = threading.Thread(target=_run_server, daemon=True)
server_thread.start()

# Wait until the server is ready
for _ in range(30):
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            break
    except OSError:
        time.sleep(0.1)
else:
    raise RuntimeError("FastAPI server failed to start")
