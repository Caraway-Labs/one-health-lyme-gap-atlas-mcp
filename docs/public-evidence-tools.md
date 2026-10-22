# Original public evidence tool contracts

The full catalog now contains nine tools; see [the five research additions](research-tools.md).
The original tools are documented here with the reviewed MCP #42 context extension below.

Audience: public-health epidemiologists/researchers and developers of AI research
applications. Anonymous public evidence only. Tool descriptions and schemas are
registered deterministically alongside `atlas_resolve_geographies`: four original tools.
MCP #27 intentionally retires `server_status` and `atlas_smoke_test`, breaking
clients that invoke them. The SDK rejects both names as unknown tools; no alias
is provided. This supersedes earlier operational inventory decisions while
preserving historical ADR records and all four domain contracts.

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

`atlas_get_county_profile`: exact five ASCII-digit `county_fips`, plus 1-3 unique
`selections`, each containing exact `measure_id`, `year` OR inclusive `start_date`
and `end_date` OR `vintage_year`, and optional `page_token`. Explicit date ranges cover at most 31
days. Each selection fetches at most 31 observations, with a continuation token.
Annual selection does not coerce cumulative evidence into an annual measure.
`scapularis_status` and `burgdorferi_status` require the published cumulative
selection `start_date=end_date=2025-12-31`, never an annual year. County context
requires `vintage_year=2022` for `population_2022`, `svi_percentile_2022`,
`uninsured_percent_2022`, and `uninsured_percentile_2022`; `rucc_2023` requires
`vintage_year=2023`. Vintage excludes all annual/date fields. Invalid selections
fail with corrective validation guidance before retrieval; no date is substituted.
Population/SVI/insurance preserve their ACS 2018-2022 reference period. RUCC
preserves null dates and its authoritative category label, never an annual period.
These are descriptive county context, not causal or individual-risk evidence.
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
MCP #44 permits at most three additional downstream operations to wait at most one
second for an existing slot, within the unchanged whole-tool deadline. Queue-full,
wait-timeout and tool-capacity rejection return retryable RATE_LIMITED with
reason=temporary_capacity and retry_after_seconds. No server-side retries occur.
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

Busy-period guidance: prefer sequential semantic tool calls. For a retryable
capacity rejection, wait at least retry_after_seconds (or HTTP Retry-After), add
jitter, and retry the unchanged request once. If still busy, stop and report the
request_id. Never launch parallel retries or retry INVALID_REQUEST,
UPSTREAM_CONTRACT_INVALID, RELEASE_CHANGED or other non-retryable failures.
request_budget identifies the retained rolling/ingress request protection;
publisher_rate_limit identifies an upstream 429, preserving numeric Retry-After
(bounded to 1–3600 seconds, default 60). These are transport states, not missing
scientific observations. Existing 30/60 ingress, eight active HTTP, three active
tools/data calls and 50 downstream requests/minute ceilings remain enforced.

## Verification and schema ownership

`contracts/public-api-schema.json` bundles unchanged reachable components of the
API public OpenAPI, with source commit and file digest. Runtime validation is local,
with no schema URL dereference. To refresh, extract the same five response roots
and transitive references from an approved API OpenAPI revision and run fidelity,
schema, protocol and live acceptance gates. Never import API runtime dependencies.

Run repository gates and `python -m atlas_lyme_mcp.check_client` for discovery and
schema validation, retired-name rejection, county resolution and post-call HTTP
health. Offline CI supplies a test-only local reference; deployed checks use the
real publisher. `/healthz` proves process health only; initialization, `tools/list`
and a domain invocation provide protocol/discovery/execution proof. `python -m atlas_lyme_mcp.acceptance` opt-in verifies real
data and API/MCP fidelity at `MCP_URL`; it is never part of ordinary offline CI.
Release receipt belongs outside source with exact deployed SHA/protocol and outputs.

Input property descriptions are published in MCP `tools/list`, including nested
selection and geography fields. Evidence argument models use Pydantic `Field`
metadata. Geography registration uses `geography_input_schema()` to describe the
input projection without changing the shared `requested` response schema.
The HTTP protocol regression test
checks client-visible descriptions through official SDK discovery.

CI runs `tests/test_metadata_quality.py` in the existing Pytest quality job.
It initializes the production ASGI application and decodes the actual HTTP
`tools/list` JSON without SDK defaults masking absent metadata. The reusable
`tests/metadata_gate.py` validates the four-tool inventory, useful tool/input
prose, self-contained Draft 2020-12 schemas and all four domain annotations.
Input traversal covers nested objects, arrays, nullable/composed schemas and
local JSON-pointer references (including cycles); repeated constraint-only
properties inherit their enclosing declaration. New branch properties and
unused definitions are checked too. Remote schema retrieval is prohibited.
Diagnostics identify the tool and property path needing correction.

`tests/fixtures/mcp-catalog-contract.json` records the serialized contract from
main `7e99775794126adef17161696d9172970acc4d57` before #23. It freezes all input
metadata except description prose, annotations, and canonical SHA-256 digests
of complete output schemas (sorted-key JSON, Python default separators).
This preserves types, required/default fields, literals, bounds, exclusivity
branches and unknown-property restrictions without duplicating scientific
schemas. Output descriptions are included in those digests. Issue #25 updates
only the four domain output digests; #27 removes only the two retired entries,
leaving every remaining baseline value and digest unchanged; the field-level review is in
`tests/fixtures/output-schema-25-review.json`.
Intentional contract changes require review before updating this fixture; never
regenerate it merely to silence a failure. Description checks reject blanks,
name echoes and common placeholders; human review still assesses prose quality.
Mutation regressions verify the gate itself without modifying runtime sources.
Existing runtime validators and their tests remain authoritative for constraints
that JSON Schema does not express, such as valid dates and cursor coupling.


## MCP output interpretation (#25)

Discovery lists published indicators and bounded related measure pages; it does
not establish county availability. Continue `meta.next_page_token` as `page_token`,
and each `meta.measure_page_tokens` entry with its `indicator_id` and
`measure_page_token`. Check both continuation channels. A county profile has a
separate `next_page_token` for each echoed measure-period selection; continue it
with the same county, measure, period and release. Success does not mean all
scientific pages have been retrieved.

`retrieval_state=empty` means no observations on this selection page, never zero
incidence or biological absence. `returned` means observation records exist,
including records with null scientific values. Preserve the API distinctions
between reported zero, missing, suppressed and unavailable evidence; MCP does
not redefine the canonical Observation or its value-state taxonomy.

`meta.release_id` is derived from returned resources. It can be null when unknown,
including all-empty discovery or all-empty profile selections. Do not invent a
release or treat this as historical snapshot support. Matching releases establish
lineage consistency, not scientific comparability across measures, periods or
populations. `meta.response_at` is the API response construction time; profiles
retain the last selection page's timestamp. It is not source freshness. Provenance
returns the exact source or methodology for the expected current release; a
mismatch fails. Keep the original observation: provenance metadata alone does
not establish it. Null source timestamps remain unknown. Provenance wrappers
have no response timestamp field.

Inspect the error layer before interpreting evidence:

- A successful call with empty evidence or continuation tokens is a normal result.
- Geography statuses are per-item domain outcomes inside successful calls;
  `unavailable` is not a scientific missingness state.
- Execution failures set `CallToolResult.isError=true`; inspect the sanitized
  error code and retry guidance, rather than validating it as a success payload.
- SDK/JSON-RPC failures (for example invalid arguments or unknown tools) can occur
  outside a successful `CallToolResult` and are not empty observations.
- HTTP ingress rate limiting may return HTTP 429 before tool execution; an upstream
  rate limit can instead become a tool-level `RATE_LIMITED` error. Neither is evidence.

New schema declarations for existing wrapper fields are annotation-only (no new
`type`, `required`, enum or bounds). Removing descriptions and empty annotation-only
property declarations yields exactly the prior validation contract. Scientific
components remain pinned and byte-for-byte unchanged; missing scientific prose
belongs to separately reviewed API work, followed by an explicit synchronization.

## Reviewed vintage/context extension (MCP #42)

This explicit contract revision adds the mutually exclusive vintage selection to
profile, comparison and brief inputs, and a separately typed county-context
observation alternative to their outputs. Existing dated Observation components
remain unchanged. `contracts/context-api-schema.json` pins the complete reachable
context collection from API commit `1c3979acd0618d6f2db9477d9766237683d907ce`,
with the export digest. Output schemas namespace these canonical components to
avoid replacing any older dated component. The required `county_context` field
discriminates context rows; runtime validation selects the canonical collection
from the requested selection rather than guessing from a response.

Preserve county_context vintage, source field, definition, category label, allowed
states and metadata methodology alongside all original source/evidence/version
references and limitations. Response fidelity verifies the requested county,
measure and vintage, release, evidence identity and valid original period shape.
Null category dates are not fabricated. Profile, comparison and brief input
snapshots change. Profile and all five research output digests change because
research outputs embed the common component bundle. Scientific dated
schemas, geography input, inventory, annotations and service budgets do not.

Regression fixtures prove transport behavior, not published availability.
Real-client Pennsylvania workflow acceptance on both approved hostnames remains
required after exact-SHA deployment. This extension implements the already
accepted API vintage contract (API ADR 0018), not a new source or score method.
