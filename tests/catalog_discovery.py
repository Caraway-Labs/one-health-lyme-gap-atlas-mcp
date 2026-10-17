"""Exercise the production ASGI transport, without any external service calls."""

from typing import Any

from starlette.testclient import TestClient

from atlas_lyme_mcp.config import Settings
from atlas_lyme_mcp.server import create_app


def discover_catalog() -> list[dict[str, Any]]:
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1:8000") as client:
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "metadata-ci", "version": "1"},
                },
            },
        )
        initialized.raise_for_status()
        assert "result" in initialized.json(), "MCP initialization failed"
        headers["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]
        response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        response.raise_for_status()
        result = response.json()["result"]
        assert not result.get("nextCursor"), "tools/list is paginated; collect every page"
        tools: list[dict[str, Any]] = result["tools"]
        return tools
