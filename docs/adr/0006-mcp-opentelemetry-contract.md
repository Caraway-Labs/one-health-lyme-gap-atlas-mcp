# 0006: MCP OpenTelemetry and operational telemetry contract

Status: Accepted
Date: 2026-10-23
Decision owner: Atlas product and engineering owner

## Context

MCP already emits one-line JSON `atlas_mcp_outcome` events and forwards
`X-Request-ID` and inbound `traceparent` to the API. Tempo stores API spans,
but MCP itself exports no spans, so tool completion failures with HTTP 200
upstream are hard to see in Grafana alone (incident 2026-10-21, parent #45).

## Decision

Export optional OTLP HTTP traces with `service.name=atlas-lyme-mcp`, using the
shared package's `configure_tracing` / `flush_tracing` / `shutdown_tracing`.
Tracing is best-effort and must never prevent the server from starting.

Span contract (schema version `1`, attribute `atlas.telemetry.schema_version`):

| Span | Kind | Name | Bounded attributes |
| --- | --- | --- | --- |
| Tool | internal SERVER-like | `atlas.mcp.tool.<tool>` | `atlas.mcp.tool`, `atlas.mcp.outcome`, `atlas.mcp.reason`, `atlas.mcp.retryable`, `atlas.mcp.deadline_ms` (20000) |
| Upstream API | CLIENT | `atlas.mcp.upstream.<resource>` | `atlas.mcp.resource`, `http.status_code` when known, outcome/reason |
| Ingress rejection | internal | `atlas.mcp.ingress` | `atlas.mcp.ingress.cause` in `per_client_rate`, `global_rate`, `active_mcp_requests`, `client_table_full` |

Every span carries `request.id` from the MCP request context. When no inbound
`traceparent` is present, the active tool span becomes the trace root and the
client injects W3C context into upstream API calls.

Logs remain `atlas_mcp_outcome` JSON on the telemetry logger; spans complement
but do not replace them. No tool arguments, bodies, IPs or free text in spans.

App Platform receives `OTEL_EXPORTER_OTLP_ENDPOINT` and a secret
`OTEL_EXPORTER_OTLP_HEADERS` matching the existing observability pilot.

## Consequences

Operators can correlate MCP tool outcomes with API dependency spans in Tempo.
A Grafana dashboard and Loki shipper target are provisioned separately in the
Atlas infra repository.

## Alternatives considered

Browser or web-app tracing was rejected for this release. Replacing JSON logs
with spans-only telemetry was rejected because Loki panels and `operations.py`
depend on the existing event shape.
