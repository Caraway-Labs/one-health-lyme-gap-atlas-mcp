# 0002: MCP as a peer adapter over portable Atlas domain contracts

Status: Proposed
Date: 2026-09-27
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

The existing MCP development service proves Streamable HTTP and operational tool invocation. Future Atlas capabilities need shared contracts without making MCP a mandatory REST proxy or a second persistence backend. The shared-python repository owns portable domain logic; Atlas services own governed infrastructure and runtime policy.

## Decision

REST and MCP are peer interface adapters. MCP tools express semantic agent tasks rather than mirror REST endpoints one for one. A tool module owns MCP schema and registration, then delegates non-transport behavior to a small in-process application/orchestration seam. That seam may use `lyme_gap_atlas_shared.domain` for stable, deterministic, infrastructure-independent models, validation, and calculations:

```text
MCP tool/orchestration
        |
        v
lyme_gap_atlas_shared.domain
        |
        v
portable validation / model / calculation
```

MCP need not call REST merely to reuse pure Python logic. When a capability needs governed data, persistence, runtime credentials, Neo4j, Snowflake, ML serving, or service-owned policy, the application seam calls an approved Atlas API/service client:

```text
semantic MCP tool -> application orchestration -> approved Atlas API/service
                                               -> governed infrastructure
```

No new deployed component is implied by an in-process application layer. A future service client may own its service URL, authentication, HTTP errors, timeouts, bounded retries, and contract mapping only after the corresponding requirements and security review. This decision creates no live data call, authentication scheme, or domain tool.

The following paths are forbidden in MCP production code:

```text
MCP -> Snowflake
MCP -> Neo4j
MCP -> lyme_gap_atlas_shared.infrastructure
MCP -> deprecated shared Snowflake compatibility shims
MCP -> hidden persistence package
```

The portable shared-python base distribution is the only approved dependency surface. Do not request its `snowflake`, `observability`, or `legacy` extras. Authentication and real data-bearing tools need separate requirements and security review.

## Future-tool decision checklist

1. Is the behavior deterministic and independent of infrastructure? Use the approved shared domain implementation locally.
2. Does it need governed data or service-owned behavior? Use an approved Atlas API/service boundary.
3. Would it require direct Snowflake/Neo4j access, shared infrastructure imports, or another persistence package? Stop and seek a separate recorded architecture decision.
4. Is the result a semantic task useful to an agent? If so, define a bounded MCP tool contract.
5. Is it merely a REST endpoint renamed as a tool? Reconsider the agent-facing contract.
6. Does it expose sensitive, user-specific, or write behavior? Obtain separate authentication, authorization, and security requirements before implementation.

## Consequences

MCP can reuse versioned pure logic without a network hop. Governed infrastructure remains with approved services. Future tool implementations must make the local-versus-service choice explicit and test that production imports and dependencies do not create hidden persistence access.

## Alternatives considered

A REST-only wrapper would add network calls for portable logic. Direct database clients or shared infrastructure imports would create a second persistence boundary. Neither matches the peer-adapter decision.

## Acceptance criteria

- Repository guidance identifies REST and MCP as peer adapters and gives the local/shared versus remote/service rule.
- Direct and hidden persistence are explicitly prohibited.
- Existing `/mcp`, `/healthz`, `server_status`, and `atlas_smoke_test` behavior is unchanged.

## Rollout, observability, and rollback

This decision changes documentation only. Subsequent stories add the dependency and structural seams under separate review. Revert this ADR only through a superseding architecture decision.

## Links to affected contracts and tests

- [Epic #11](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-mcp/issues/11) and [Story #12](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-mcp/issues/12)
- `README.md`, `AGENTS.md`, existing `tests/test_server.py` and `tests/test_mcp_protocol.py`
