"""Tool completion is distinct from healthy HTTP status and rejected arguments."""

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from atlas_lyme_mcp.application.client import REQUEST_ID, TRACEPARENT, AtlasClient
from atlas_lyme_mcp.server import create_server
from atlas_lyme_mcp.tools.evidence import EvidenceTools


def events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "atlas_lyme_mcp.application.telemetry"
    ]


def test_http_200_contract_failure_has_one_failed_tool_event_and_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    request_id = REQUEST_ID.set("fixture-request-45")
    trace = TRACEPARENT.set("00-" + "a" * 32 + "-" + "b" * 16 + "-01")
    try:
        client = AtlasClient(
            "https://api.onehealthatlas.org",
            httpx.MockTransport(
                lambda _: httpx.Response(200, json={"secret": "never log private backend text"})
            ),
        )
        asyncio.run(
            create_server(client=client).call_tool(
                "atlas_get_atlas_scores", {"county_fips": ["42029"]}
            )
        )
    finally:
        REQUEST_ID.reset(request_id)
        TRACEPARENT.reset(trace)
    records = events(caplog)
    assert [(r["stage"], r["outcome"]) for r in records] == [
        ("upstream_api", "UPSTREAM_CONTRACT_INVALID"),
        ("mcp_tool", "UPSTREAM_CONTRACT_INVALID"),
    ]
    assert records[0]["http_status"] == 200
    assert records[1]["name"] == "atlas_get_atlas_scores"
    assert all(
        r["request_id"] == "fixture-request-45" and r["trace_id"] == "a" * 32 for r in records
    )
    assert "never log private" not in " ".join(r.message for r in caplog.records)
    assert "secret" not in json.dumps(records)


def test_unsupported_selection_is_logged_without_backend_call_or_arguments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("backend called")

    server = create_server(
        client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(forbidden))
    )
    with pytest.raises(ToolError, match="is cumulative"):
        asyncio.run(
            server.call_tool(
                "atlas_get_county_profile",
                {
                    "county_fips": "42029",
                    "selections": [{"measure_id": "scapularis_status", "year": 2023}],
                },
            )
        )
    records = events(caplog)
    assert len(records) == 1 and records[0]["outcome"] == "INVALID_REQUEST"
    assert records[0]["reason"] == "invalid_input"
    assert "42029" not in json.dumps(records) and "scapularis_status" not in json.dumps(records)


def test_early_capacity_rejection_gets_a_tool_outcome(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client = AtlasClient("https://api.onehealthatlas.org")
    # Retrieve the shared runtime through a small isolated adapter instead of external I/O.
    runtime = EvidenceTools(client)
    runtime.active = 3
    from atlas_lyme_mcp.tools.contracts import StrictMetadata
    from atlas_lyme_mcp.tools.research_contracts import ScoresArguments

    async def blocked(county_fips: list[str]) -> Any:
        async def forbidden() -> dict[str, Any]:
            raise AssertionError("overloaded work started")

        return await runtime.invoke("atlas_get_atlas_scores", forbidden())

    metadata = StrictMetadata(tool_name="atlas_get_atlas_scores", arg_model=ScoresArguments)
    result = asyncio.run(metadata.call_fn(blocked, True, {"county_fips": ["42029"]}))
    assert result.is_error
    assert len(events(caplog)) == 1 and events(caplog)[0]["outcome"] == "RATE_LIMITED"
