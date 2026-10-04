import os
import time
import uuid

import httpx
import pytest

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
CONTENT_URL = os.environ.get("CONTENT_URL", "http://localhost:8000")
WEB_URL = os.environ.get("WEB_URL", "http://localhost:8081")


@pytest.fixture(scope="session")
def api():
    with httpx.Client(base_url=GATEWAY_URL, timeout=10) as c:
        yield c


@pytest.fixture()
def author():
    """A fresh author per test: tests never see each other's data."""
    return f"contract-{uuid.uuid4().hex[:12]}"


def eventually(check, timeout: float = 20.0, interval: float = 0.25):
    """Poll `check` until it returns a truthy value; for asynchronous effects such as indexing."""
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result or time.monotonic() > deadline:
            return result
        time.sleep(interval)
