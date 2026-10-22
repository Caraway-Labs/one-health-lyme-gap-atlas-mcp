# Five bounded research tools (#35)

The public catalog contains nine tools. The four existing contracts stay unchanged.
These five tools compose anonymous, read-only approved REST capabilities; they do
not query databases, persist results, score observations, or fetch caller URLs.

| Tool | Arguments | Maximum REST calls | Successful response |
| --- | --- | --- | --- |
| `atlas_compare_counties` | 2-5 distinct exact `county_fips`; 1-3 unique `selections` | 15 | Per-selection county matrix, original observations and availability metadata, common release, explicit comparability caveat |
| `atlas_get_surveillance_priority` | 1-5 distinct exact `county_fips` | 5 | Original availability and persisted Tier 1 result per county, comparison caveat |
| `atlas_get_atlas_scores` | 1-5 distinct exact `county_fips`; optional current `dataset_version` | 6 | Original county detail and release metadata, publisher scores, coverage and limitations |
| `atlas_review_state` | Valid uppercase state/DC postal `state`; optional current `dataset_version` | 1 | Original review, methodology/config digest, evaluation time, coverage, gaps and limitations |
| `atlas_build_evidence_brief` | Exact `county_fips`; 1-3 unique `selections` | 9 | Exact scope, canonical evidence, source/method resources, original evidence references, gaps, caveats and request ID |

A selection uses an exact published `measure_id` and either `year` (1900-2100)
or both ISO dates (at most 31 inclusive days). Unknown properties, duplicate
selections/counties, encoded JSON strings and ambiguous periods are rejected.
Comparison and brief exclude continuation input. Each selection retrieves at most
31 observations. An advertised additional page fails with `EVIDENCE_INCOMPLETE`;
it never produces an apparently complete partial matrix or brief. Narrow the
selection; use the existing profile tool for explicit page-by-page exploration.
Unknown release identity, missing governed methodology or more than six distinct
source/method references also fails a brief explicitly. No citation is fabricated.

All tools retain the shared 256 KiB upstream/result cap, 20-second whole-tool
deadline, HTTP timeout (15 seconds, 2-second connect), no retries, at most three
active tool operations, and 50 downstream requests/minute. Fan-out uses batches of at most three under a shared client-wide three-request cap.
The new bounded call budgets apply only to these five tools. The original discovery,
profile and provenance budgets remain six, three and one. These operations can
fail safely under slow upstream responses or the global rate budget; no limit is
silently relaxed. Request IDs propagate through the existing REST client.

## Scientific interpretation

Original observations retain ZERO, MISSING, SUPPRESSED, UNAVAILABLE, NO_RECORDS
and NO_COUNTY_LINKED_RECORD semantics. Empty evidence never establishes biological
absence. Every row includes the original selection, retrieval state and canonical
availability metadata. Matching releases do not establish comparability. Comparison
flags differing county period/grain/unit/method signatures; it never ranks counties,
tests significance or makes epidemiological conclusions. Original limitations,
source/method identifiers and dates remain attached to observations.

Tier 1 output is surveillance **review priority**, not predicted disease risk,
incidence, probability or clinical advice. NO_PUBLISHED_MODEL is confirmed
publication absence; operational errors remain errors. NOT_ESTIMABLE retains null
scores/tiers; INSUFFICIENT remains distinct from abstention. Percentiles refer only
to the publisher batch population; matching batch identifiers alone do not prove
comparability. Geography release and ML source release are different lineages and
are preserved independently. Mixed ML source releases fail closed.

Atlas gap scores remain publisher scores, separate from Tier 1. The public
`/v1/atlas/scores` accepts only dataset/settings and returns an unbounded national
collection. `/v1/atlas/ranking.csv` has no limit/pagination. Therefore this tool uses
`GET /v1/counties/{fips}` and `/v1/atlas/metadata` for explicit county selection only.
API commit `e6ac966788e899099da5c30f6540a98dab834636`, `service.py` lines 68-108,
shows both score collection and county detail call the same `_summary` with the
same score settings. County detail includes original geographic identity, publisher
score/priority and release methodology. No label or rank is invented. Ranked
selections are not supported. Metadata and county release objects must match.

The `atlas-county-review@1.0.0` rules remain disabled. An `unsupported` review is
returned unchanged with its coverage and data gaps; it is never interpreted as
`none_stand_out`, disease risk or outbreak identification.

Briefs resolve every non-null source/method reference against the observation
release, preserve original evidence IDs and list empty/missingness states explicitly.
Source timestamps remain unknown when null. Response/evaluation/batch timestamps
are not substituted for source freshness. No PDF, new inference, literature search,
clinical advice or evidence graph capability is introduced.

## Contract synchronization and compatibility

`contracts/research-api-schema.json` contains unchanged reachable components from
public API OpenAPI at the commit above, with a SHA-256 of the normalized LF export.
The old public schema file and four serialized tool contract entries stay unchanged.
The current API adds optional observation collection metadata (`availability`,
`reason`, `release_id`, `limitations`). Runtime envelope validation explicitly
accepts this reviewed schema; scientific Observation properties are unchanged
(the required-field array is reordered only). Existing profile wrappers retain
their original fields; new tools additionally preserve full selection metadata.
Unreviewed upstream fields still fail closed. There is no remote schema dereference.

Live example fixtures are public publisher snapshots retrieved on 2026-10-18;
regressions may deliberately mutate them and identify synthetic resources locally.
They are test examples, not newly admitted source data or proof of future releases.
The catalog baseline retains all four old input/schema/annotation entries exactly;
only the five new entries are added.

## Examples and verification

### Scores compatibility repair (MCP #41)

The reviewed additions in `contracts/research-api-schema.json` retain
`scoring_methodology_version` on both `AtlasMetadata` and `CountyDetail`.
The county's nested `release` uses that same metadata component. The property
is copied unchanged from API commit `1c3979acd0618d6f2db9477d9766237683d907ce`
and checked against the published OpenAPI on 2026-10-22. The original bundle
source identity is retained; `reviewed_additions` identifies this later field
synchronization separately. Nullable schema spelling and required-field order
changes in the newer export do not change accepted values and are not copied.

Older payloads may omit this API-defaulted property; MCP never invents it.
Present values must match the published methodology literal. All original
release, methodology and limitations fields remain intact. Unknown properties
and unreviewed methodology versions still fail closed, with request-ID guidance
and no claim of missing disease evidence. No score is recalculated.

The five research catalog output digests change because each contains the same
component bundle; their only scientific schema change is these two optional
properties. The original four catalog contracts are unchanged. Regression tests
cover both Pennsylvania FIPS, old payloads, nested release metadata and hostile
fields/versions. Local fixtures are transport tests, not deployed acceptance.
Release still requires the exact reviewed deployed SHA and the Pennsylvania
workflow through a real MCP client on both approved hostnames.

```json
{"county_fips":["01001","01003"],"selections":[{"measure_id":"case_count_floor_2023","year":2023}]}
```

Use the example above with `atlas_compare_counties`. For a brief use one
`county_fips` string and the same selections. Priority and scores accept
`{"county_fips":["09110"]}`. Review accepts `{"state":"CT"}`.
These are reproducible requests, not promises that the current release has evidence.

Run all README quality gates and `python -m atlas_lyme_mcp.check_client` for official
SDK discovery of nine tools. Run `python -m atlas_lyme_mcp.research_acceptance` on the exact
reviewed build and both approved deployed hosts; save its structured receipt outside
source. A safe error is not a successful scientific example. Existing four-tool
acceptance remains required separately. Preserve any real upstream prerequisite
and keep #35 open until all five tools and deployed acceptance succeed.

## Rollout and rollback

Owner review of the new public contract and bounded budgets was recorded on
2026-10-18 (accepted ADR 0005). Use the existing controlled DigitalOcean flow; do not
change app topology, access, credentials, source admission or other production jobs.
Deploy only the reviewed merged SHA. Verify that SHA from App Platform, health,
raw catalog parity, official SDK invocation and bounded API/MCP parity on both hosts.
Rollback by deploying the previously reviewed main source through the existing
runbook, verifying the prior four-tool catalog and health. Preserve the issue branch
and worktree if any required acceptance or gate remains unresolved.
