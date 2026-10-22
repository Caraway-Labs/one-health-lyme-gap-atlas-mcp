"""Evidence concurrency stays bounded, ordered, complete, and cancellable."""

import asyncio
import copy
from typing import Any

import httpx
import pytest
from mcp_types import CallToolResult
from test_evidence_tools import fixture

from atlas_lyme_mcp.application.bounded import bounded
from atlas_lyme_mcp.application.client import AtlasClient, RetrievalError
from atlas_lyme_mcp.server import create_server


def test_bounded_order_and_failure_cancels_remaining_work() -> None:
    async def check() -> None:
        active = peak = finished = 0
        barrier = asyncio.Event()

        async def operation(i: int) -> dict[str, Any]:
            nonlocal active, peak, finished
            active += 1
            peak = max(active, peak)
            if active == 3:
                barrier.set()
            try:
                await barrier.wait()
                await asyncio.sleep(0)
                finished += 1
                return {"index": i}
            finally:
                active -= 1

        values = await asyncio.wait_for(bounded([operation(i) for i in range(8)]), 10)
        assert values == [{"index": i} for i in range(8)]
        assert peak == 3 and active == 0 and finished == 8
        cancelled = asyncio.Event()

        async def failure() -> dict[str, Any]:
            await asyncio.sleep(0)
            raise RetrievalError("UPSTREAM_UNAVAILABLE", True)

        async def waiting() -> dict[str, Any]:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return {}

        with pytest.raises(RetrievalError):
            await bounded([failure(), waiting(), waiting(), waiting()])
        assert cancelled.is_set()

    asyncio.run(check())


@pytest.mark.parametrize("tool", ["atlas_discover_indicators", "atlas_compare_counties"])
def test_three_retrievals_overlap_without_losing_order_or_pagination(tool: str) -> None:
    async def check() -> None:
        active = peak = calls = 0
        barrier = asyncio.Event()
        ids = [f"indicator{i}" for i in range(5)]

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active, peak, calls
            if request.url.path.endswith("indicators"):
                page = fixture("indicators")
                base = page["data"][0]
                page["data"] = []
                for identifier in ids:
                    row = copy.deepcopy(base)
                    row.update(indicator_id=identifier, measure_ids=[identifier + "_measure"])
                    page["data"].append(row)
                page["meta"]["next_page_token"] = "next-indicator-page"
                return httpx.Response(200, json=page)
            active += 1
            calls += 1
            peak = max(peak, active)
            if active == 3:
                barrier.set()
            try:
                await barrier.wait()
                if tool == "atlas_discover_indicators":
                    page = fixture("measures")
                    identifier = request.url.params["indicator_id"]
                    row = page["data"][0]
                    row.update(indicator_id=identifier, measure_id=identifier + "_measure")
                    page["data"] = [row]
                    page["meta"]["next_page_token"] = "next-" + identifier
                else:
                    page = fixture("observations")
                    page["data"][0]["geography"]["geography_id"] = request.url.params[
                        "geography_id"
                    ]
                    page["data"][0]["measure_id"] = request.url.params["measure_id"]
                return httpx.Response(200, json=page)
            finally:
                active -= 1

        server = create_server(
            client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
        )
        args: dict[str, Any] = (
            {"page_size": 5}
            if tool == "atlas_discover_indicators"
            else {
                "county_fips": ["01001", "01003"],
                "selections": [{"measure_id": f"measure{i}", "year": 2023} for i in range(3)],
            }
        )
        result = await asyncio.wait_for(server.call_tool(tool, args), 10)
        assert isinstance(result, CallToolResult)
        assert not result.is_error, result
        assert peak == 3 and active == 0
        if tool == "atlas_discover_indicators":
            assert calls == 5
            assert [m["indicator_id"] for m in result.structured_content["measures"]] == ids
            assert result.structured_content["meta"]["next_page_token"] == "next-indicator-page"
            assert result.structured_content["meta"]["measure_page_tokens"] == {
                i: "next-" + i for i in ids
            }
        else:
            assert calls == 6
            assert result.structured_content["complete"] is True
            assert [r["request"]["measure_id"] for r in result.structured_content["matrix"]] == [
                f"measure{i}" for i in range(3)
            ]
            assert all(
                [c["county_fips"] for c in r["counties"]] == ["01001", "01003"]
                for r in result.structured_content["matrix"]
            )

    asyncio.run(check())


def test_connection_session_reused_and_closed_on_failure() -> None:
    async def check() -> None:
        client = AtlasClient(
            "https://api.onehealthatlas.org", httpx.MockTransport(lambda _: httpx.Response(503))
        )
        session = None
        with pytest.raises(RetrievalError):
            async with client.lifespan():
                session = client._session
                async with client._http_client() as reused:
                    assert reused is session
                assert session is not None and not session.is_closed
                await client.get("atlas_metadata", None, "research:AtlasMetadata")
        assert session is not None and session.is_closed
        assert client._session is None and client.active == 0

    asyncio.run(check())
