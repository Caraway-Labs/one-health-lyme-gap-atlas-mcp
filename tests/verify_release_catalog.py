"""Opt-in raw remote catalog comparison against the reviewed local app and gate."""

import json
import os
from pathlib import Path

import httpx
from catalog_discovery import discover_catalog
from metadata_gate import validate_catalog


def verify() -> None:
    url = os.environ["MCP_URL"]
    if url not in {
        "https://mcp.onehealthatlas.org/mcp",
        "https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp",
    }:
        raise ValueError("Use an approved existing public endpoint")
    headers = {"Accept": "application/json, text/event-stream"}
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        initialized = client.post(
            url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "release-catalog", "version": "1"},
                },
            },
        )
        initialized.raise_for_status()
        headers["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]
        response = client.post(
            url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
        )
        response.raise_for_status()
        result = response.json()["result"]
        assert not result.get("nextCursor")
        baseline = json.loads(
            (Path(__file__).parent / "fixtures/mcp-catalog-contract.json").read_text()
        )
        validate_catalog(result["tools"], baseline)
        expected = {tool["name"]: tool for tool in discover_catalog()}
        actual = {tool["name"]: tool for tool in result["tools"]}
        assert actual == expected, "Remote metadata differs from reviewed local app"
        print(f"{url}: nine complete tool contracts match reviewed app and baseline")


if __name__ == "__main__":
    verify()
