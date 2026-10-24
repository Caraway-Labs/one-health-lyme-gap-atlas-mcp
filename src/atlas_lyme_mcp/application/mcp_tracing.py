"""Optional OpenTelemetry spans for MCP tools, upstream API calls and ingress limits."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import Status, StatusCode

SCHEMA_VERSION = "1"
TOOL_DEADLINE_MS = 20000


def _tracer() -> trace.Tracer:
    return trace.get_tracer("atlas_lyme_mcp")


IngressCause = Literal[
    "per_client_rate",
    "global_rate",
    "active_mcp_requests",
    "client_table_full",
]


def _request_id_attr() -> str:
    from atlas_lyme_mcp.application.client import REQUEST_ID

    value = REQUEST_ID.get()
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value) else "unavailable"


def _base_attrs() -> dict[str, str | int]:
    return {
        "atlas.telemetry.schema_version": SCHEMA_VERSION,
        "request.id": _request_id_attr(),
    }


def inject_upstream_trace(headers: dict[str, str]) -> None:
    """Propagate the active span when the MCP client did not supply traceparent."""
    from atlas_lyme_mcp.application.client import TRACEPARENT

    if TRACEPARENT.get():
        return
    carrier: dict[str, str] = {}
    inject(carrier)
    if traceparent := carrier.get("traceparent"):
        headers["traceparent"] = traceparent


@contextmanager
def tool_span(tool: str) -> Iterator[dict[str, str]]:
    """Record final outcome/reason on the span in the caller's finally block."""
    state = {"outcome": "OK", "reason": "completed", "retryable": "false"}
    name = f"atlas.mcp.tool.{tool}" if tool else "atlas.mcp.tool.unknown"
    with _tracer().start_as_current_span(
        name,
        attributes={
            **_base_attrs(),
            "atlas.mcp.tool": tool if tool else "unknown",
            "atlas.mcp.deadline_ms": TOOL_DEADLINE_MS,
        },
    ) as span:
        try:
            yield state
        finally:
            span.set_attribute("atlas.mcp.outcome", state["outcome"])
            span.set_attribute("atlas.mcp.reason", state["reason"])
            span.set_attribute("atlas.mcp.retryable", state["retryable"])
            if state["outcome"] == "OK":
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(Status(StatusCode.ERROR))


@contextmanager
def upstream_span(resource: str) -> Iterator[dict[str, str | int | None]]:
    state: dict[str, str | int | None] = {
        "outcome": "OK",
        "reason": "completed",
        "http_status": None,
    }
    name = f"atlas.mcp.upstream.{resource}"
    with _tracer().start_as_current_span(
        name,
        kind=trace.SpanKind.CLIENT,
        attributes={**_base_attrs(), "atlas.mcp.resource": resource},
    ) as span:
        try:
            yield state
        finally:
            span.set_attribute("atlas.mcp.outcome", str(state["outcome"]))
            span.set_attribute("atlas.mcp.reason", str(state["reason"]))
            status = state.get("http_status")
            if isinstance(status, int):
                span.set_attribute("http.status_code", status)
            if state["outcome"] == "OK":
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(Status(StatusCode.ERROR))


@contextmanager
def ingress_rejection_span(cause: IngressCause) -> Iterator[None]:
    with _tracer().start_as_current_span(
        "atlas.mcp.ingress",
        attributes={**_base_attrs(), "atlas.mcp.ingress.cause": cause},
    ) as span:
        span.set_status(Status(StatusCode.ERROR))
        yield
