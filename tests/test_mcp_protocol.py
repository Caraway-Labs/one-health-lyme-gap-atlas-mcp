"""Exercise the actual HTTP transport with the official MCP client."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from atlas_lyme_mcp.check_client import check


@pytest.fixture
def running_server() -> Iterator[int]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port), "MCP_ALLOWED_HOSTS": ""}
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas_lyme_mcp.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("MCP server exited before becoming healthy")
            try:
                with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("MCP server did not become healthy")
        yield port
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def test_http_initialize_discover_and_invoke(
    running_server: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MCP_URL", f"http://127.0.0.1:{running_server}/mcp")
    asyncio.run(check())
    output = capsys.readouterr().out
    assert "MCP initialized:" in output
    assert "atlas_smoke_test" in output
    assert "server_status" in output
    assert "Atlas MCP is alive on DigitalOcean." in output
