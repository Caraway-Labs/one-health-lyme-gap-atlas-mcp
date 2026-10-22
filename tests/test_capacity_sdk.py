"""Exercise the locked SDK's real plain-JSON HTTP 429 transport boundary offline."""

import asyncio
import json
from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from atlas_lyme_mcp.research_workflow import Workflow, capacity_recovery


class MockServer:
    def __init__(self, reject_again: bool = False, retry_header: str | None = "60") -> None:
        self.calls: list[dict[str, Any]] = []
        self.reject_again, self.retry_header = reject_again, retry_header

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        message = json.loads(request.content)
        method = message["method"]
        if method == "notifications/initialized":
            return httpx2.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "offline-plain429", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "atlas_discover_indicators",
                        "inputSchema": {"type": "object"},
                        "outputSchema": {"type": "object"},
                    }
                ]
            }
        elif method == "tools/call":
            self.calls.append(
                {"arguments": message["params"], "request_id": request.headers.get("X-Request-ID")}
            )
            if len(self.calls) == 1 or self.reject_again:
                headers = (
                    {"Retry-After": self.retry_header} if self.retry_header is not None else {}
                )
                return httpx2.Response(
                    429,
                    headers=headers,
                    json={
                        "code": "RATE_LIMITED",
                        "request_id": request.headers.get("X-Request-ID"),
                        "retryable": True,
                        "retry_after_seconds": 60,
                        "reason": "temporary_capacity",
                        "message": "private body must not be copied",
                    },
                )
            value: dict[str, Any] = {"meta": {}}
            result = {
                "content": [{"type": "text", "text": json.dumps(value)}],
                "structuredContent": value,
                "isError": False,
            }
        else:
            raise AssertionError(f"Unexpected offline method: {method}")
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})


def test_locked_sdk_plain_json_429_discards_http_retry_metadata() -> None:
    async def check() -> None:
        server = MockServer()
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)) as http:
            transport = streamable_http_client(
                "https://mcp.onehealthatlas.org/mcp", http_client=http
            )
            async with Client(transport, mode="legacy") as client:
                await client.list_tools()
                with pytest.raises(MCPError) as caught:
                    await client.call_tool("atlas_discover_indicators", {"page_size": 1})
                assert caught.value.error.code == -32603
                assert caught.value.error.message == "Server returned an error response"
                assert caught.value.error.data is None
        assert len(server.calls) == 1

    asyncio.run(check())


def test_real_sdk_plain_429_stops_full_workflow_and_retains_observed_header() -> None:
    async def check() -> None:
        server = MockServer()
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)) as http:
            transport = streamable_http_client(
                "https://mcp.onehealthatlas.org/mcp", http_client=http
            )
            async with Client(transport, mode="legacy") as client:
                tools = await client.list_tools()
                workflow = Workflow(
                    client, http, {tool.name: tool.output_schema for tool in tools.tools}
                )
                result = await workflow.run()
        assert len(server.calls) == 1
        assert result["stopped_reason"] == "capacity_rejected"
        assert result["calls"][0]["outcome"] == "RATE_LIMITED"
        assert result["calls"][0]["result"]["retry_after_seconds"] == 60
        assert "private body" not in json.dumps(result)

    asyncio.run(check())


@pytest.mark.parametrize(
    "reject_again, header, expected_calls",
    [(False, "60", 2), (True, "60", 2), (False, None, 1), (False, "invalid", 1)],
)
def test_real_sdk_recovery_is_one_retry_from_observed_header_only(
    reject_again: bool, header: str | None, expected_calls: int
) -> None:
    async def check() -> None:
        server = MockServer(reject_again, header)
        waits = []

        async def wait(seconds: float) -> None:
            waits.append(seconds)

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)) as http:
            transport = streamable_http_client(
                "https://mcp.onehealthatlas.org/mcp", http_client=http
            )
            async with Client(transport, mode="legacy") as client:
                tools = await client.list_tools()
                workflow = Workflow(
                    client, http, {tool.name: tool.output_schema for tool in tools.tools}
                )
                result = await capacity_recovery(workflow, wait=wait, jitter=lambda: 0.125)
        assert len(server.calls) == expected_calls
        assert waits == ([60.125] if expected_calls == 2 else [])
        assert result["recovered"] is (expected_calls == 2 and not reject_again)
        assert result["calls"][0]["outcome"] == "RATE_LIMITED"
        assert len({call["request_id"] for call in server.calls}) == expected_calls
        assert all(call["arguments"] == server.calls[0]["arguments"] for call in server.calls)
        if header in (None, "invalid"):
            assert result["calls"][0]["result"]["retry_after_seconds"] is None
        assert "private body" not in json.dumps(result)

    asyncio.run(check())
