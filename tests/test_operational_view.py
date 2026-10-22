"""Existing logs expose task failures without exposing arbitrary log fields."""

import json
from datetime import UTC, datetime

from atlas_lyme_mcp.operations import parse_event, summarize
from atlas_lyme_mcp.research_workflow import render


def test_operational_view_separates_api_status_from_tool_success_and_alerts() -> None:
    now = datetime.now(UTC)
    lines = []
    for i in range(5):
        base = {
            "event": "atlas_mcp_outcome",
            "timestamp": now.isoformat(),
            "name": "atlas_get_atlas_scores",
            "stage": "mcp_tool",
            "outcome": "UPSTREAM_CONTRACT_INVALID" if i < 3 else "OK",
            "reason": "contract_invalid" if i < 3 else "completed",
            "duration_ms": 100 + i,
            "request_id": f"request-{i}",
            "secret": "never expose this log field",
        }
        lines.append(json.dumps(base))
        lines.append(
            json.dumps(
                {
                    **base,
                    "stage": "upstream_api",
                    "name": "atlas_metadata",
                    "http_status": 200,
                    "outcome": "OK",
                    "reason": "completed",
                }
            )
        )
    result = summarize(lines, request_id="request-0", now=now)
    assert result["alert"] is True and result["tool_calls"] == 5 and result["tool_failures"] == 3
    assert len(result["groups"]) == 2 and len(result["request_events"]) == 2
    assert result["request_events"][1]["http_status"] == 200
    assert "never expose" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


def test_invalid_or_unbounded_log_records_are_rejected() -> None:
    assert parse_event("private arbitrary text") is None
    assert parse_event("x" * 65537) is None
    assert parse_event(json.dumps({"event": "different", "secret": "private"})) is None


def test_incomplete_workflow_never_becomes_a_disease_absence_or_complete_recommendation() -> None:
    report = render(
        {"complete": False, "failures": ["atlas_compare_counties:UPSTREAM_UNAVAILABLE"]}
    )
    assert "workflow incomplete" in report
    assert "not zero disease evidence" in report
    assert "No complete allocation recommendation is claimed" in report
