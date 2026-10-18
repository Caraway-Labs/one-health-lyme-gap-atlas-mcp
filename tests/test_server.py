"""Server behavior without any external Atlas dependency."""

import asyncio
import importlib
from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from atlas_lyme_mcp.config import Settings
from atlas_lyme_mcp.server import create_app, create_server


def test_config_defaults(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    for key in ("HOST", "PORT", "MCP_ALLOWED_HOSTS"):
        monkeypatch.delenv(key, raising=False)
    assert Settings.from_env() == Settings()


def test_config_overrides(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "example.org, example.org:*")
    assert Settings.from_env() == Settings("127.0.0.1", 9123, ("example.org", "example.org:*"))


def test_application_and_health() -> None:
    assert create_server(Settings()) is not None
    with TestClient(create_app(Settings())) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unlisted_host_is_rejected_by_mcp() -> None:
    settings = Settings(allowed_hosts=("mcp.example.org", "mcp.example.org:*"))
    with TestClient(create_app(settings), base_url="https://mcp.example.org") as client:
        allowed = client.post("/mcp", json={})
        rejected = client.post("/mcp", json={}, headers={"Host": "other.example.org"})
    assert allowed.status_code != 421
    assert rejected.status_code == 421


def test_import_has_no_process_side_effect() -> None:
    with patch("uvicorn.run") as run:
        import atlas_lyme_mcp.server as module

        importlib.reload(module)
    run.assert_not_called()


@pytest.mark.parametrize(
    "host,expected",
    [
        ("mcp.example.org", 200),
        ("mcp.example.org:443", 200),
        ("legacy.example.org", 200),
        ("legacy.example.org:443", 200),
        ("other.example.org", 421),
        ("child.mcp.example.org", 421),
        ("mcp.example.org:444", 421),
    ],
)
def test_additive_exact_hosts(host: str, expected: int) -> None:
    settings = Settings(
        allowed_hosts=(
            "mcp.example.org",
            "mcp.example.org:443",
            "legacy.example.org",
            "legacy.example.org:443",
        )
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "host-check", "version": "1"},
        },
    }
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/mcp",
            json=payload,
            headers={"Host": host, "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == expected


@pytest.mark.parametrize("name", ["server_status", "atlas_smoke_test"])
def test_retired_tools_are_unknown(name: str) -> None:
    server = create_server(Settings())
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 9
    assert name not in {tool.name for tool in tools}
    with pytest.raises(ToolError, match=f"Unknown tool: {name}"):
        asyncio.run(server.call_tool(name, {}))
