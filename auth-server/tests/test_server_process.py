"""Starts a real uvicorn process.

In-process tests share one setup task, so they can't see failures that appear
only when lifespan and requests run in different tasks. Tortoise 1.x connections
are one such failure: every test passed while the real server had no database.
"""

import socket
import subprocess
import sys
import time

import httpx
import pytest


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server():
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                httpx.get(f"{url}/health/live", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            pytest.fail("Server did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_real_server_reaches_its_database_from_a_request(server):
    response = httpx.get(f"{server}/health/ready", timeout=5)
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "database": "up", "redis": "up"}


def test_real_server_guards_included_routes(server):
    response = httpx.get(f"{server}/v1/admin/users", timeout=5)
    assert response.status_code == 401


def test_real_server_refuses_a_forged_token(server):
    response = httpx.get(
        f"{server}/v1/admin/applications",
        headers={"Authorization": "Bearer forged"},
        timeout=5,
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_token"
