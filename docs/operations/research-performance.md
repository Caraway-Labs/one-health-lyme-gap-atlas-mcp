# Bounded research retrieval (MCP #43)

The October 21 incident demonstrates whole-tool failures despite eventual HTTP
success. Discovery now overlaps up to three independent measure pages. Profiles
overlap selections; comparisons flatten county/selection retrieval into one ordered
three-worker schedule, avoiding nested fanout. The schedule cancels and drains all
started work on failure and closes unstarted operations. Returned order, pagination,
release checks, canonical observations/citations and explicit unavailable evidence
remain unchanged. A failed dependency never becomes a partial successful comparison.

The production ASGI lifespan owns one approved-origin HTTP client with at most three
connections/keepalives, closing it on shutdown. Import and direct test construction
have no startup or network side effects. Redirects, environment proxy trust,
authentication, origin allowlist and timeout settings are unchanged. Request/trace
headers are set separately for every call. No evidence cache is introduced: this
avoids inventing freshness or caching a no-store/unavailable response.

## Separately justified comparison result budget

On 2026-10-22, three real-MCP comparisons of 42029/42091 with January 2025 temperature
and precipitation plus 2025 forest returned RESULT_TOO_LARGE in approximately
19.66, 19.45 and 19.05 seconds. Four public climate pages each contained 31 rows
and measured 88,125–88,969 bytes; both forest selections were explicit unavailable
collections. Replaying these six captured canonical API pages through the actual
comparison application, including all evidence and limitations, produced **370,540
encoded result bytes**, release `governed-2026-10-15-january-climate-prod`.
This replay establishes size, not live MCP latency or task acceptance.

The reviewed proposal increases only `atlas_compare_counties`' encoded structured
result allowance from 256 KiB to **512 KiB**. The text fallback duplicates that
structured content, so transport size is larger; it remains bounded. All upstream
bodies, every other tool result, input bodies, requests/minute, three active data
calls, tool concurrency, HTTP concurrency, and 20s/15s/2s deadlines stay unchanged.
Larger comparisons still fail atomically with RESULT_TOO_LARGE. Tests cover a
complete comparison above 256 KiB, rejection above 512 KiB, and unchanged profile
and upstream caps. No evidence is removed or compressed into an opaque payload.
This exception needs explicit review alongside the #43 performance change.

## Reproducible measurements

Run from the exact source checkout:

```sh
uv run python scripts/benchmark_research.py --url https://mcp.onehealthatlas.org/mcp --source-sha <deployed-sha> --output <receipt.json>
```

The harness issues six bounded official-SDK calls: first discovery/comparison,
warm discovery/comparison, then one concurrent pair. It preserves complete
structured results, continuation tokens, availability reasons and latency/error
outcomes. It never retries or disguises errors as evidence. First/warm describe
invocation order; a remote process/API cache is not assumed cold. For process-cold
measurement, run against a newly started production app on loopback with the real
approved API; record startup separately. Runtime success requires no error,
three complete comparison selections, both requested counties and no continuation.
Discovery is one five-indicator page and must retain both pagination channels.

The pre-change live discovery first/warm/concurrent timings were 20.36s (failed),
12.08s and 16.78s. These are a small incident reproduction sample, not an SLO.
Concurrent capacity/retry behavior remains tracked separately by #44. Publish
post-change first/warm/concurrent receipts from both deployed hosts before closing
#43; health, mock scheduling tests and direct API size reads do not establish this.
