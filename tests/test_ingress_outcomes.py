"""Rejected HTTP requests are correlated separately from executed tools."""

import asyncio
import json
import logging

import httpx
import pytest
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from atlas_lyme_mcp.application.telemetry import record
from atlas_lyme_mcp.operations import summarize
from atlas_lyme_mcp.protection import PublicProtection


@pytest.mark.parametrize("capacity", [False, True])
def test_ingress_rejections_are_correlated_and_alert_separately(
    capacity: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    async def check() -> None:
        entered = 0
        ready = asyncio.Event()
        release = asyncio.Event()

        async def admitted(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal entered
            entered += 1
            if capacity:
                if entered == 8:
                    ready.set()
                await release.wait()
            record("mcp_tool", "atlas_get_atlas_scores", "OK", "completed", 1)
            await JSONResponse({"ok": True})(scope, receive, send)

        app = PublicProtection(admitted)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pending = []
            if capacity:
                pending = [asyncio.create_task(client.post("/mcp")) for _ in range(8)]
                await asyncio.wait_for(ready.wait(), 5)
            else:
                for _ in range(30):
                    assert (await client.post("/mcp")).status_code == 200
            try:
                for i in range(3):
                    response = await client.post(
                        "/mcp",
                        content="private-body-42029",
                        headers={"X-Request-ID": f"rejected-{i}"},
                    )
                    assert response.status_code == 429
                    assert response.json()["request_id"] == f"rejected-{i}"
                    assert response.headers["Retry-After"] == "60"
            finally:
                release.set()
                await asyncio.gather(*pending)
        assert app.active == 0
        assert entered == (8 if capacity else 30)

    asyncio.run(check())
    lines = [r.message for r in caplog.records if r.name == "atlas_lyme_mcp.application.telemetry"]
    summary = summarize(lines, request_id="rejected-1")
    assert summary["ingress_rejections"] == 3
    assert summary["ingress_alert"] and summary["alert"]
    assert summary["tool_calls"] == (8 if capacity else 30)
    assert summary["tool_failures"] == 0 and not summary["tool_alert"]
    events = summary["request_events"]
    assert len(events) == 1
    assert events[0]["stage"] == "public_ingress"
    assert events[0]["name"] == "mcp"
    assert events[0]["outcome"] == "RATE_LIMITED"
    assert events[0]["http_status"] == 429
    assert events[0]["reason"] == ("temporary_capacity" if capacity else "request_budget")
    assert "private-body" not in json.dumps(lines) and "42029" not in json.dumps(lines)
