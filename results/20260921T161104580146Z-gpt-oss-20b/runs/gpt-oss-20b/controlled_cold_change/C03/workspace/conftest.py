import os
import threading
import time
import pytest
import uvicorn
from stockflow.main import app

os.environ["BASE_URL"] = "http://127.0.0.1:8000"


def _run_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="error")
    server = uvicorn.Server(config)
    server.run()

@pytest.fixture(scope="session", autouse=True)
def start_server():
    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()
    # Wait a bit to ensure server is ready
    time.sleep(1)
    yield

