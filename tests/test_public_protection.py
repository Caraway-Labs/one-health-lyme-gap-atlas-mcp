"""Exercise SDK transport rejection and the deployed single-instance workload bounds."""

import json
from typing import Any

import pytest
from starlette.testclient import TestClient

from atlas_lyme_mcp.config import Settings
from atlas_lyme_mcp.server import create_app

INITIALIZE: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "transport-test", "version": "1"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Host": "other.example.org"}, 421),
        ({"Origin": "https://unapproved.example.org"}, 403),
        ({"MCP-Protocol-Version": "unsupported"}, 400),
        ({"Content-Type": "text/plain"}, 400),
    ],
)
def test_sdk_security_negatives(headers: dict[str, str], expected: int) -> None:
    app = create_app(Settings(allowed_hosts=("mcp.example.org",)))
    with TestClient(app, base_url="https://mcp.example.org") as client:
        response = client.post("/mcp", json=INITIALIZE, headers=HEADERS | headers)
    assert response.status_code == expected


def test_sdk_body_limit_and_anonymous_rate_limit() -> None:
    app = create_app(Settings(allowed_hosts=("mcp.example.org",)))
    with TestClient(app, base_url="https://mcp.example.org") as client:
        oversized = client.post("/mcp", json=INITIALIZE | {"padding": "x" * 16384}, headers=HEADERS)
        assert oversized.status_code == 413
        for _ in range(29):
            assert client.post("/mcp", json=INITIALIZE, headers=HEADERS).status_code == 200
        rejected = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
        assert rejected.status_code == 429
        assert rejected.headers["Retry-After"] == "60"
        assert "RATE_LIMITED" in rejected.text
        assert client.get("/healthz").status_code == 200


def test_http_tool_validation_has_no_backend_side_effect() -> None:
    app = create_app(Settings(allowed_hosts=("mcp.example.org",)))
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "atlas_get_county_profile",
            "arguments": {"county_fips": "1001", "selections": [{"measure_id": "x", "year": 2023}]},
        },
    }
    with TestClient(app, base_url="https://mcp.example.org") as client:
        response = client.post("/mcp", json=request, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    assert "county_fips" in json.dumps(response.json())
