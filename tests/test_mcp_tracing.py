"""OpenTelemetry span contract for MCP tools and upstream calls."""

import json

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from atlas_lyme_mcp.application.client import REQUEST_ID
from atlas_lyme_mcp.application.mcp_tracing import ingress_rejection_span, tool_span, upstream_span
from atlas_lyme_mcp.server import create_server


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def test_mcp_span_contract(span_exporter: InMemorySpanExporter) -> None:
    request_id = REQUEST_ID.set("trace-test-req")
    try:
        with tool_span("atlas_discover_indicators") as tool_state:
            tool_state["outcome"] = "OK"
            tool_state["reason"] = "completed"
            with upstream_span("indicators") as upstream_state:
                upstream_state["http_status"] = 200
                upstream_state["outcome"] = "OK"
        with ingress_rejection_span("global_rate"):
            pass
    finally:
        REQUEST_ID.reset(request_id)

    names = [span.name for span in span_exporter.get_finished_spans()]
    assert "atlas.mcp.tool.atlas_discover_indicators" in names
    assert "atlas.mcp.upstream.indicators" in names
    assert "atlas.mcp.ingress" in names
    spans = span_exporter.get_finished_spans()
    tool = next(s for s in spans if s.name.startswith("atlas.mcp.tool"))
    assert tool.attributes
    assert tool.attributes.get("atlas.telemetry.schema_version") == "1"
    assert tool.attributes.get("request.id") == "trace-test-req"
    ingress = next(s for s in span_exporter.get_finished_spans() if s.name == "atlas.mcp.ingress")
    assert ingress.attributes is not None
    assert ingress.attributes.get("atlas.mcp.ingress.cause") == "global_rate"
    assert "secret" not in json.dumps(dict(tool.attributes))


def test_server_starts_without_otel_environment() -> None:
    assert create_server() is not None
