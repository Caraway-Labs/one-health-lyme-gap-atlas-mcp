# Batch county identity resolution

`atlas_resolve_geographies` accepts a strict `geographies` array with 1–4 entries.
Each entry has exactly `county_fips` (five ASCII digits, string) or `county` and
`state` (nonblank strings, at most 128 characters). Extra fields, null values,
numeric FIPS, empty batches and five-item batches fail request validation.

Example: `{"geographies":[{"county":"Ada","state":"Idaho"},{"county":"Valley","state":"ID"}]}`.
Case and whitespace are normalized; the canonical `County` suffix is optional.
Other county equivalents require their complete canonical name (for example,
`Baltimore city`). No punctuation rewriting, fuzzy matching, city/ZIP geocoding
or implicit scientific comparison occurs. Duplicate inputs retain positional
results. Every input returns `input_index`, unchanged `requested` fields,
`status`, nullable `geography`, `candidates` (at most four), and nullable `reason`.
Ambiguity never chooses a candidate; candidates are a bounded preview rather
than necessarily an exhaustive list. Unknown names/states/FIPS return
`not_found`; failed or invalid references return `unavailable`.

## Authoritative source and architecture

The existing Data-owned `county-identity-geometry-v1` contract identifies
CDC/ATSDR SVI 2022 USA county layer as the source of `STCNTY`, `COUNTY`, `STATE`
and `ST_ABBR`. MCP reads only these four public attributes from the same fixed
publisher FeatureServer; geometry and scientific attributes are excluded.
It neither copies a registry into source control nor accesses infrastructure.
Shared `domain.normalize_county_fips` validates identifiers locally. The public
Atlas `/v1/geographies` route remains unavailable; it is not a lookup fallback.

This is a bounded publisher-service reader, not an ingestion/promotion pipeline
or new maintained geography database. No API/shared/Data code changes occur.
The adopted source and field meanings are reused; matching is a narrow MCP
identity task because no shared name lookup currently exists.

The reader requests two ordered pages of at most 2,000 records, a combined
one MiB maximum, five-second HTTP timeouts and a 12-second fetch deadline.
Redirects are rejected. Exactly 3,144 unique FIPS and 51 consistent state
identities are required, matching the existing contract US states/DC scope.
Territories are outside this source scope. Changed/incomplete source scope fails
closed and requires a reviewed correction; records are not fabricated.

The in-memory cache expires after one hour; one lock prevents concurrent
refreshes. Failed refreshes have a 30-second cooldown and never serve expired
references. No persistent file/database or background refresh exists. Existing
anonymous HTTP request/concurrency budgets apply.

Top-level `reference` supplies the publisher layer URL, fixed 2022 dataset ID,
actual UTC retrieval time and SHA-256 of the sorted canonical identity projection
(JSON with sorted keys). It is shared by every resolved/ambiguous/not-found item
in the batch. Unavailable batches have null reference. This digest identifies
the actual retrieved attributes; it is not the Data pipeline full GeoJSON
artifact checksum or Atlas release ID. State FIPS is the first two characters
of the verified county FIPS.

Identity means membership in this 2022 reference. It establishes neither current
legal boundaries nor observations, evidence adequacy, risk, disease absence or
comparability. Scientific evidence remains API-owned.

## Verification and release

Run README quality gates and hosted Docker/protocol checks. Focused offline
tests verify behavior; they do not prove genuine county mappings. Source-backed
acceptance after exact reviewed-source deployment:

```powershell
$env:MCP_URL = "https://mcp.onehealthatlas.org/mcp"
uv run python -m atlas_lyme_mcp.check_client
uv run python -m atlas_lyme_mcp.geography_acceptance
uv run python -m atlas_lyme_mcp.acceptance
```

Geography acceptance invokes single, two and four-item requests, mixed failure,
and leading-zero FIPS, comparing identities/digest with a fresh publisher read.
Existing evidence acceptance verifies original tools. Record actual production
results. Rollback redeploys the previously reviewed source through the runbook.


## Interpreting outcomes

`resolved` supplies one canonical reference identity. `ambiguous` supplies a
limited candidate preview and requires clarification; never automatically choose
one. `not_found` means no match in the valid reference. `unavailable` means the
reference could not be retrieved or validated, not that a county does not exist.
Inspect every ordered item, its zero-based `input_index`, echoed `requested`,
nullable `geography`, `candidates` and categorical `reason`. The shared reference
is null when unavailable. The SVI 2022 version, identity-projection checksum and
actual reference retrieval time describe identity lineage, not Atlas scientific
release, observation availability or freshness. A successful MCP call can contain
unresolved items; protocol errors, tool `isError` and HTTP rate limits are separate
layers described in the public evidence tool contract.
