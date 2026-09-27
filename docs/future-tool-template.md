# Future semantic MCP tool checklist

Keep `server.py` responsible for MCP construction and registration. Put MCP-facing schemas and a thin callable in `tools/`. Put task orchestration in `application/`, where it can be tested without MCP transport. Import only portable contracts or pure logic from `lyme_gap_atlas_shared.domain`.

For the first approved service-backed tool, add a narrowly scoped client module under `atlas_lyme_mcp.clients` (create the package when there is a real approved service contract). The application function may combine that client with portable shared-domain logic. The client owns the approved service URL, authentication, HTTP errors, timeout, bounded retry policy, and contract mapping specified by that tool's separate requirements. No generic client or live data request exists in this story, and this in-process structure adds no deployed component.

```text
server.py registration -> tools/<semantic_task>.py -> application/<task>.py
                                                    |-> lyme_gap_atlas_shared.domain
                                                    |-> clients/<approved_service>.py
```

Before implementing a capability:

1. Is the behavior pure, stable, and independent of infrastructure? Use shared-python locally.
2. Does it need governed runtime data or service-owned behavior? Call an approved Atlas API/service through a bounded client.
3. Does it need direct Snowflake or Neo4j, shared infrastructure imports, or hidden persistence? Stop; a separate ADR is required.
4. Is the proposed tool a semantic task useful to an agent? Define its bounded MCP input and output contract.
5. Is it only a REST endpoint renamed as a tool? Reconsider the agent task and tool contract.
6. Does it expose private, user-specific, or write behavior? Obtain separate product, authentication, authorization, and security requirements first.

Preserve source, retrieval time, geography, methodology/version, and limitations in any future data-bearing result. Add independent application tests, MCP transport/contract tests, failure tests for approved service calls, and provenance/security checks required by that tool's contract. Do not use this template as authorization to expose domain data.
