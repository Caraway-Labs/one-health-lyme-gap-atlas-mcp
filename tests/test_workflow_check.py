"""Workflow control never equates a late response or bounded crawl with completion."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest
from mcp import Client
from mcp_types import CallToolResult, TextContent

from atlas_lyme_mcp.research_workflow import Workflow


class ScriptedClient:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value, self.calls = value, 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        self.calls += 1
        return CallToolResult(
            structured_content=self.value,
            content=[TextContent(type="text", text=json.dumps(self.value))],
        )


def test_late_complete_response_is_retained_but_fails_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 21.0])
    monkeypatch.setattr(
        "atlas_lyme_mcp.research_workflow.time", SimpleNamespace(monotonic=lambda: next(clock))
    )

    async def check() -> None:
        client = ScriptedClient({"fixture": "complete public result"})
        async with httpx2.AsyncClient() as http:
            workflow = Workflow(cast(Client, client), http, {"fixture_tool": {"type": "object"}})
            assert await workflow.call("fixture_tool", {}) is None
            assert workflow.calls[0]["outcome"] == "LATE_COMPLETION"
            assert workflow.calls[0]["result"] == client.value
            assert workflow.failures and client.calls == 1

    asyncio.run(check())


def test_discovery_bound_is_explicit_incomplete_not_silent_truncation() -> None:
    async def check() -> None:
        client = ScriptedClient({"meta": {"next_page_token": "more", "measure_page_tokens": {}}})
        async with httpx2.AsyncClient() as http:
            workflow = Workflow(
                cast(Client, client), http, {"atlas_discover_indicators": {"type": "object"}}
            )
            await workflow.discovery()
            assert client.calls == 3
            assert workflow.failures == ["indicator pagination bound reached; catalog incomplete"]

    asyncio.run(check())
