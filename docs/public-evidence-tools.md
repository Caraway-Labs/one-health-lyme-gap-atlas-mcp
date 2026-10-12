# Public evidence tool contract

Audience: public-health epidemiologists/researchers and developers of AI research
applications. Anonymous public evidence only. Tool descriptions and schemas are
registered deterministically alongside `server_status` and `atlas_smoke_test`.

## Tool arguments and results

`atlas_discover_indicators`: optional exact `indicator_id`, `page_size` 1–5
(default 3), `page_token`. Returns unmodified `indicators`, their associated
unmodified `measures`, and `meta` with `release_id`, backend `response_at`,
`next_page_token`, and `measure_page_tokens` keyed by indicator ID. Each indicator
fetches one measure page of at most 20; no automatic full-catalog crawl. Continue a
measure page with exact `indicator_id` and `measure_page_token`, excluding
`page_token`. Backend cursors retain their canonical query/release binding.
Discovery states published definitions, never county availability. Empty selections
return empty lists and unknown/null release identity; do not fabricate availability.

`atlas_get_county_profile`: exact five ASCII-digit `county_fips`, plus 1–3 unique
`selections`, each containing exact `measure_id`, `year` OR inclusive `start_date`
and `end_date`, and optional `page_token`. Explicit date ranges cover at most 31
days. Each selection fetches at most 31 observations, with a continuation token.
Annual selection does not coerce cumulative evidence into an annual measure.
Returns `county_fips`, `selections` (original request, canonical observations,
`retrieval_state=returned|empty`, `next_page_token`) and `meta` with release and
response time. Different selection periods remain independent; they establish no
comparability. No county names are inferred. Empty results are not missing rows,
zero, biological absence, or verified county identity. One upstream failure fails
the tool with no partial evidence or claimed complete profile.

`atlas_get_evidence_provenance`: `reference_type=source|methodology`, exact
`reference_id`, and required `expected_release_id`. Returns unmodified canonical
`resource`, its type/ID and release. This resolves current source/methodology
metadata, not arbitrary observation IDs or historical releases. Keep the original
observation/evidence reference for citation. Null source publication, update,
retrieval or ingestion timestamps remain unknown, distinct from response time.

All arguments are strict JSON types, with unknown fields rejected. IDs are bounded
ASCII identifiers; slash/URL/path traversal is rejected. Profile FIPS uses the
approved shared-Python validation locally. The response keeps canonical API data,
including versions, denominators, exact decimal strings, public evidence references,
source URLs, timestamps, optional environmental/surveillance context and limitations.
MISSING/SUPPRESSED/UNAVAILABLE null values, ZERO, NO_RECORDS and
NO_COUNTY_LINKED_RECORD retain their distinct API meanings. No records is not absence.

## Service and workload boundary

`ATLAS_API_ORIGIN` is the approved public HTTPS origin only; no caller-supplied host,
credentials, private endpoint or URL fetching. Fixed GET routes: indicators,
measures, observations, source detail and methodology detail. Redirects disabled.
The explicit production activation authorizes this non-secret public origin.

Bounds: 16 KiB MCP body via SDK; 256 KiB per upstream body and structured result;
at most six discovery, three profile or one provenance backend calls per tool;
20s whole-tool deadline, 15s HTTP/read timeout and 2s connect timeout, no retries;
three active data calls per instance; 50 downstream requests per rolling minute.
Anonymous HTTP protection: 30 requests/minute per connecting address, 60 global,
eight active HTTP requests and at most 1024 salted in-memory client keys. Forwarded
addresses are not trusted. No address, argument body or upstream text is logged.
These budgets fit the existing one-instance deployment; reevaluate before scaling.

Results/errors have matching structured content and JSON text fallback. Execution
failures set MCP `isError=true` with code, generic message, retryable, request_id,
and optional retry_after_seconds. Codes include INVALID_REQUEST, RESOURCE_NOT_FOUND,
RATE_LIMITED, UPSTREAM_UNAVAILABLE, UPSTREAM_CONTRACT_INVALID, RELEASE_CHANGED,
RESULT_TOO_LARGE. SDK handles invalid schemas/unknown tools/protocol errors.
HTML 504 and backend 503 become sanitized unavailable errors, never observations.
No raw backend errors or private proof are returned. API #88 gateway remediation
remains API-owned and does not block supported human-evidence retrieval.

## Verification and schema ownership

`contracts/public-api-schema.json` bundles unchanged reachable components of the
API public OpenAPI, with source commit and file digest. Runtime validation is local,
with no schema URL dereference. To refresh, extract the same five response roots
and transitive references from an approved API OpenAPI revision and run fidelity,
schema, protocol and live acceptance gates. Never import API runtime dependencies.

Run repository gates and `python -m atlas_lyme_mcp.check_client` for discovery and
operational regression. `python -m atlas_lyme_mcp.acceptance` opt-in verifies real
data and API/MCP fidelity at `MCP_URL`; it is never part of ordinary offline CI.
Release receipt belongs outside source with exact deployed SHA/protocol and outputs.
