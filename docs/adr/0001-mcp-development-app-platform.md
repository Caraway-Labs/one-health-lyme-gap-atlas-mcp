# 0001: MCP development proof on DigitalOcean App Platform

Status: Proposed
Date: 2026-09-26
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

Atlas needs an external proof that a local MCP client can invoke its containerized Python server. The existing Atlas deployment decision uses controlled GitHub-sourced App Platform applications in the TopX Lyme Challenge project. Epic #4 explicitly authorizes a temporary, public, unauthenticated development proof.

## Decision

Deploy one `oh-lyme-mcp-dev` App Platform web service in `sfo`, assigned to the existing TopX Lyme Challenge project. App Platform builds the repository Dockerfile from reviewed `main`; source auto-deployment is disabled. Use one `apps-s-1vcpu-0.5gb` instance and DigitalOcean-managed HTTPS on its generated hostname. The service offers `/healthz` and stateless Streamable HTTP at `/mcp`. Its only MCP tools are `server_status` and `atlas_smoke_test`.

Set `MCP_ALLOWED_HOSTS` to the exact generated App Platform domain, with the optional port form. Preserve the MCP SDK's DNS-rebinding protection. Requests without an `Origin` remain valid. Configure an explicit Origin only if an observed, expected client requires it; do not add browser CORS middleware for this proof.

## Consequences

The endpoint is publicly reachable without authentication and must remain limited to harmless operational responses. It contains no Atlas data, secrets, database access, persistence, external network calls, or write-capable tools. This decision does not approve production use, authentication design, domain-tool access, or a service-level commitment. The one-instance current-plan tier is approximately $5 per month while running; confirm pricing before creation.

## Alternatives considered

Building and pushing to a registry adds credentials and an image release path. A Droplet or Kubernetes cluster adds maintenance and infrastructure. Feature-branch deployment would expose unreviewed code. None is needed for this proof.

## Acceptance criteria

- The tracked App Platform spec validates and builds the reviewed merged `main` commit through the existing Dockerfile.
- The app is healthy over HTTPS; a remote official MCP client initializes, lists, and invokes both tools with the exact smoke response.
- A local Cursor client shows the actual remote tool-call result, corroborated by application logs.
- The deployed source SHA equals the reviewed merge SHA and no secret or domain-data tool is introduced.

## Rollout, observability, and rollback

Run local and CI gates before merge; create the app only afterward. Inspect deployment phase, source SHA, health, and build/run logs. If a later deployment fails, redeploy the last reviewed working source and spec. Keep the development app available after proof; remove it only through a separately authorized cleanup.

## Links to affected contracts and tests

- [Epic #4](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-mcp/issues/4) and Stories #5–#8
- `.do/app.yaml`, `docs/operations/digitalocean-mcp.md`, `tests/test_server.py`, `tests/test_mcp_protocol.py`
- Workspace ADR 0004, DigitalOcean deployment and DNS
