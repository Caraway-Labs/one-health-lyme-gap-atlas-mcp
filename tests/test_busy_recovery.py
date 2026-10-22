"""Bounded capacity waits recover without raising active/request limits or retrying errors."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from atlas_lyme_mcp.application.client import AtlasClient, RetrievalError
from atlas_lyme_mcp.tools.evidence import EvidenceTools


def metadata() -> dict[str, Any]:
    return dict(json.loads((Path(__file__).parent / "fixtures/research-metadata.json").read_text()))


def test_six_parallel_requests_run_with_three_active_and_bounded_waiting() -> None:
    async def check() -> None:
        active = peak = 0
        release = asyncio.Event()
        entered = asyncio.Event()

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 3:
                entered.set()
            try:
                await release.wait()
                return httpx.Response(200, json=metadata())
            finally:
                active -= 1

        client = AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
        calls = [
            asyncio.create_task(client.get("atlas_metadata", None, "research:AtlasMetadata"))
            for _ in range(3)
        ]
        await entered.wait()
        waiting = [
            asyncio.create_task(client.get("atlas_metadata", None, "research:AtlasMetadata"))
            for _ in range(3)
        ]
        await asyncio.sleep(0)
        assert client.waiting == 3 and client.active == 3
        with pytest.raises(RetrievalError) as rejected:
            await client.get("atlas_metadata", None, "research:AtlasMetadata")
        assert rejected.value.reason == "temporary_capacity"
        assert rejected.value.retryable and rejected.value.retry_after_seconds == 1
        assert len(client.calls) == 3
        release.set()
        results = await asyncio.gather(*calls, *waiting)
        assert len(results) == 6 and peak == 3
        assert client.active == client.waiting == 0
        # One bounded retry of the capacity rejection succeeds after capacity recovers.
        assert await client.get("atlas_metadata", None, "research:AtlasMetadata") == metadata()
        assert len(client.calls) == 7

    asyncio.run(check())


def test_cancelled_waiter_releases_queue_slot_without_downstream_call() -> None:
    async def check() -> None:
        entered = 0
        barrier = asyncio.Event()

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal entered
            entered += 1
            await barrier.wait()
            return httpx.Response(200, json=metadata())

        client = AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
        calls = [
            asyncio.create_task(client.get("atlas_metadata", None, "research:AtlasMetadata"))
            for _ in range(3)
        ]
        while entered < 3:
            await asyncio.sleep(0)
        waiter = asyncio.create_task(client.get("atlas_metadata", None, "research:AtlasMetadata"))
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        assert client.waiting == 0 and len(client.calls) == 3
        barrier.set()
        await asyncio.gather(*calls)
        assert client.active == 0

    asyncio.run(check())


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "INVALID_REQUEST", False),
        (200, "UPSTREAM_CONTRACT_INVALID", False),
        (429, "RATE_LIMITED", True),
    ],
)
def test_failures_are_classified_and_never_automatically_retried(
    status: int, code: str, retryable: bool
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Retry-After": "5"}, json={"private": "unreviewed"})

    client = AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
    with pytest.raises(RetrievalError) as failure:
        asyncio.run(client.get("atlas_metadata", None, "research:AtlasMetadata"))
    assert calls == 1 and failure.value.code == code and failure.value.retryable is retryable
    if status == 429:
        response = EvidenceTools.failure(failure.value)
        assert response.structured_content["reason"] == "publisher_rate_limit"
        assert response.structured_content["retry_after_seconds"] == 5
        assert "retry" in response.structured_content["message"]
        assert "private" not in str(response)


def test_rolling_request_budget_remains_fifty() -> None:
    client = AtlasClient("https://api.onehealthatlas.org")
    client.calls.extend([time.monotonic()] * 50)
    with pytest.raises(RetrievalError) as failure:
        asyncio.run(client.get("atlas_metadata", None, "research:AtlasMetadata"))
    assert failure.value.reason == "request_budget"
    assert failure.value.retry_after_seconds == 60
    assert len(client.calls) == 50 and client.active == 0
