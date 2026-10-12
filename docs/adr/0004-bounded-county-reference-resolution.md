# 0004: Bounded county reference resolution in the existing MCP service

Status: Accepted
Date: 2026-10-11
Decision owner: Atlas product owner (MCP #20 implementation/review/merge/deploy authorization)

## Decision

Add anonymous read-only `atlas_resolve_geographies` to the same service,
preserving five existing tools and ADR 0002 peer-adapter architecture.
Reuse portable shared FIPS validation and the existing Data-adopted CDC/ATSDR
SVI 2022 county reference through its public publisher service. No portable
name lookup exists and the canonical Atlas geography API is unavailable.

Read only county identity attributes through a fixed bounded GET boundary.
Do not duplicate a registry, import infrastructure, expose caller URLs/queries,
change scientific interpretation or modify another repository. This supplements
ADR 0003 evidence exposure with identity only.

## Contract, consequences and acceptance

[Tool contract](../geography-resolution.md): strict 1–4 inputs, deterministic
conservative matching, partial outcomes, fail-closed source scope, one-hour
memory cache, provenance and no stale fallback. No identity is inferred from
observations. Publisher 2022 vintage is explicit; current legal geography and
evidence availability are outside scope.

Source availability is a dependency. Changed scope or malformed responses
produce `unavailable`, distinct from `not_found`. Independent review checks
source identity, incorrect/ambiguous mappings, workload bounds and regressions.
Green tests/CI and real production SDK discovery/invocation against the exact
ACTIVE merged SHA are required. Rollback uses the existing DigitalOcean process.

## Alternatives

An embedded county table would create a maintained registry. The pending Atlas
geography route cannot resolve names. A generic geocoder or warehouse connection
would broaden scope and violate existing boundaries.
