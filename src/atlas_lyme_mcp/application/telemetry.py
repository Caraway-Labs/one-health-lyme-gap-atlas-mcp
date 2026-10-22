"""Small fixed-field operational events; never log tool arguments or publisher bodies."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)
TOOLS = frozenset(
    {
        "atlas_resolve_geographies",
        "atlas_discover_indicators",
        "atlas_get_county_profile",
        "atlas_get_evidence_provenance",
        "atlas_compare_counties",
        "atlas_get_surveillance_priority",
        "atlas_get_atlas_scores",
        "atlas_review_state",
        "atlas_build_evidence_brief",
    }
)
INGRESS = frozenset({"mcp"})
CODES = frozenset(
    {
        "OK",
        "INVALID_REQUEST",
        "RESOURCE_NOT_FOUND",
        "RATE_LIMITED",
        "UPSTREAM_UNAVAILABLE",
        "UPSTREAM_CONTRACT_INVALID",
        "RELEASE_CHANGED",
        "RESULT_TOO_LARGE",
        "EVIDENCE_INCOMPLETE",
        "UNEXPECTED_ERROR",
        "CANCELLED",
        "LATE_COMPLETION",
    }
)
REASONS = frozenset(
    {
        "completed",
        "invalid_input",
        "temporary_capacity",
        "request_budget",
        "publisher_rate_limit",
        "tool_deadline",
        "upstream_timeout",
        "upstream_transport",
        "contract_invalid",
        "retrieval_failed",
        "unexpected_error",
        "cancelled",
    }
)


def record(
    stage: str,
    name: str,
    outcome: str,
    reason: str,
    duration_ms: int,
    http_status: int | None = None,
) -> None:
    # Import lazily to keep the client/telemetry dependency acyclic.
    from atlas_lyme_mcp.application.client import COLLECTIONS, DETAILS, REQUEST_ID, TRACEPARENT

    allowed = (
        TOOLS
        if stage == "mcp_tool"
        else INGRESS
        if stage == "public_ingress"
        else COLLECTIONS | DETAILS
    )
    value: dict[str, Any] = {
        "event": "atlas_mcp_outcome",
        "timestamp": datetime.now(UTC).isoformat(),
        "stage": stage if stage in {"mcp_tool", "upstream_api", "public_ingress"} else "unknown",
        "name": name if name in allowed else "unknown",
        "outcome": outcome if outcome in CODES else "UNEXPECTED_ERROR",
        "reason": reason if reason in REASONS else "retrieval_failed",
        "duration_ms": max(0, duration_ms),
        "request_id": REQUEST_ID.get()
        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", REQUEST_ID.get())
        else "unavailable",
    }
    trace = TRACEPARENT.get() or ""
    if re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", trace):
        value["trace_id"] = trace.split("-")[1]
    if http_status is not None and 100 <= http_status <= 599:
        value["http_status"] = http_status
    logger.info(json.dumps(value, separators=(",", ":")))
