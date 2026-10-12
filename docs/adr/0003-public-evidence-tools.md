# 0003: Activate bounded public evidence tools in the existing MCP service

Status: Accepted
Date: 2026-10-11
Decision owner: Atlas product owner (explicit implementation, merge and deployment authorization)

## Decision

Extend the existing DigitalOcean MCP service with three anonymous read-only tools:
`atlas_discover_indicators`, `atlas_get_county_profile`, and
`atlas_get_evidence_provenance`. Preserve both operational tools and Streamable HTTP.
This supersedes ADR 0001's smoke-only exposure constraint for this bounded surface;
it does not change ADR 0002's peer-adapter architecture or shared portable boundary.

Shared `domain.normalize_county_fips` runs locally. Governed evidence is retrieved
through the approved public Atlas API origin, using fixed GET routes only. API owns
data semantics, release admission and persistence. MCP imports neither the API
package nor persistence drivers. No new service, auth platform or database exists.

## Contract and constraints

See [public evidence tools](../public-evidence-tools.md). Preserve complete canonical
public payloads, observation-specific time, source and release identities, units,
denominators, missingness and limitations. No scientific comparisons, scoring,
diagnosis, RAG, private data, SQL, writes, arbitrary paths or URLs.

API-owned schema components are extracted unchanged from public OpenAPI at
`31d9bad3b2274a5ef5ed3cffc6ba113fec03e53b`; the bundled document records its digest.
This is a pinned validation artifact, not another scientific schema authority.

## Acceptance, observability and rollback

Strict tool schemas; bounded input/output and backend requests; whole-tool deadlines;
single-instance anonymous budgets; SDK Host/Origin/version negatives; schema and
REST/MCP evidence fidelity tests; independent review and green quality/Docker CI.
After merge, deploy reviewed main to the existing app, verify its actual SHA/ACTIVE
state and both HTTPS endpoints, and invoke all three data tools with real evidence,
including missingness, provenance and a safe failure. Tool logs contain only name,
categorical outcome, duration and validated request correlation. Forward valid
traceparent and X-Request-ID using existing API conventions; no new tracing exporter.

Rollback redeploys the previously reviewed source/spec through the existing
runbook; never reset shared main or rewrite history. Preserve the starter hostname.
