# 0005: Five bounded public evidence research tools

Status: Accepted
Date: 2026-10-18
Decision owner: Atlas product and engineering owner

## Context

MCP #35 explicitly requests five anonymous read-only research tools in one release.
The existing four tools and portable shared-domain/public REST boundaries remain.
Multi-county composition needs explicit bounded fan-out and complete provenance.
The public score collection/ranking routes do not support bounded selection.

## Decision

Implement the five contracts in [research-tools.md](../research-tools.md), composing
only approved public GET capabilities through the existing client and protections.
Use exact bounded county detail for publisher scores: its `_summary` and settings
are identical to `/atlas/scores`; no ranking is exposed. Preserve disabled review
rules and all publisher evidence states and lineage. Never infer risk or citations.

Budgets are 15 comparison, 5 priority, 6 score, 1 review and 9 brief calls, with batches of at most three under a shared client request cap,
within unchanged global rate, active-operation, size and timeout caps. Original tool
budgets and published schemas are unchanged. Incomplete pagination/provenance fails
explicitly instead of silently omitting evidence. Synchronize the API's optional
collection availability metadata through a separate pinned schema bundle.

Matthew approved this decision and the stated public contracts/budgets in the task
conversation on 2026-10-18: "Yes, I approve. Please proceed." The approval explicitly
covers merge, production deployment and deployed acceptance with existing global
limits unchanged. See the [agent-recorded approval receipt](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-mcp/pull/40#issuecomment-6254459648). This records
conversation approval; it is not a GitHub review submitted as the owner.
Independent code peer review found no remaining blocking issues.

## Consequences and alternatives

No new service, persistence, authentication, credentials or access is introduced.
Expensive requests can safely fail at existing limits. A national scores dump,
unbounded CSV ranking, synthetic scores and direct database reads are rejected
alternatives. The original four tools remain compatible.

## Acceptance criteria

Nine tools discover through the official SDK; the four existing contract snapshots
remain exact. Tests cover canonical values, availability, disabled review, release
mismatches, pagination, provenance, invalid input, upstream errors/timeouts and size.
All repository gates, Docker health/protocol proof and real deployed API/MCP parity
must pass. Every one of the five tools needs a successful bounded live example.

## Rollout, observability, and rollback

Use the existing main-only reviewed DigitalOcean flow, preserve host allowlists,
verify deployed SHA and both public host catalogs, retain receipts outside source.
No claimed acceptance from process health alone. Roll back through the runbook to
the previous reviewed commit; retain recovery work when blocked.

## Links

- [Issue #35](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-mcp/issues/35)
- [ADR 0002](0002-mcp-peer-adapter-boundaries.md)
- [Public evidence contract](../public-evidence-tools.md)
- `tests/test_research_tools.py`, `tests/metadata_gate.py`
