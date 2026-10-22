# MCP research completion and correlation (MCP #45)

HTTP/process health, API HTTP status, MCP tool completion and whole research-task
completion are separate checks. A 200 API response can be rejected by the MCP
contract; successful health cannot establish usable research evidence.

## Existing-log operational view

The service writes fixed-field JSON `atlas_mcp_outcome` events to existing stdout.
`stage=mcp_tool` records validation failures, early capacity rejection, execution
results and cancellations for all nine tools through the SDK metadata seam.
`stage=upstream_api` records approved route categories, status and consumer outcome.
`stage=public_ingress`, with the fixed name `mcp`, records HTTP 429 rejections
before tool execution, preserving the returned request ID and existing budget or
capacity reason. It never reads a request body or counts a rejected request as a tool call.
No tool arguments, FIPS, cursors, source text, response bodies, client addresses,
credentials, private URLs or arbitrary exception strings enter these events.
Only approved fixed tool/route names, safe codes/reasons, duration, UTC time,
bounded request ID and validated trace ID are recorded. Existing API request/trace
headers remain unchanged. Operators can find HTTP-200/contract-invalid pairs by
request ID and follow the trace ID in the already approved trace store.

Timeout reasons distinguish whole-tool deadline from upstream timeout/transport.
A returned tool result taking more than 20 seconds is logged as LATE_COMPLETION,
not an in-budget success; its scientific result is unchanged. This detects CPU
serialization/validation that can finish after an async deadline. SDK validation
errors remain non-retryable input errors with their existing corrective guidance.
Successful geography transport still preserves individual domain outcomes; it
does not establish scientific availability.

Inspect the existing stdout export without a new backend:

```sh
uv run python -m atlas_lyme_mcp.operations --minutes 15 --request-id <request-id> < runtime.log
uv run python -m atlas_lyme_mcp.operations --minutes 15 --fail-on-alert < runtime.log
```

The bounded view considers at most 10,000 recognized events, rejects over-64-KiB
lines and unapproved labels, strips arbitrary fields, and separates tool/API
counts, reasons and p50/p95 latency. Request lookup returns at most 50 safe events.
The alert exits nonzero when a window has at least five tool calls, at least three
failures and a failure fraction of at least 20%. This is a simple reviewed
diagnostic threshold. Separately, three ingress rejections in the window trigger
an ingress alert, even when no tools executed. The combined alert is true when
either threshold is met; ingress counts and executed tool counts remain separate.
This is an operational
diagnostic threshold, not an inferred epidemiological or availability conclusion.
No source change, public metrics endpoint, centralized log service, dashboard
account, credential, scheduled polling or notification integration is created.

## Opt-in Pennsylvania task check

From the exact reviewed checkout, independently verify the active App Platform
source SHA first, then run:

```sh
uv run python -m atlas_lyme_mcp.research_workflow --source-sha <verified-deployed-sha> --output <receipt-directory>
```

The SHA is an operator-supplied label, not automatically proved by process health.
The checker uses the official real HTTPS MCP SDK on both approved hostnames, with
a unique correlation ID per sequential tool call. It executes the documented
Chester/Montgomery prompt, all bounded indicator and measure continuations,
publisher scores, cumulative tick and 2022 population profiles, January climate/
2025 forest comparison, persisted model review priority, and original source/
methodology references. It retains every raw structured result and evidence ID.
Original source vintage, periods, limitations, nulls and empty availability remain
visible. No failed retrieval becomes zero disease evidence. A brief cited response
is generated only when the bounded workflow completes; failures get an explicit
incomplete report and nonzero exit. Each tool is called once, without automatic
retries, and responses beyond 20 seconds fail task acceptance even if data returned.

A RATE_LIMITED response now stops the full workflow immediately: its original
result, request ID and attempt 1 remain in the receipt, with `stopped_reason` set
to `capacity_rejected`. No later distinct tool is sent into the same busy interval.
Completed prior calls remain in `calls`; no full recommendation is produced.

To assess recovery separately, explicitly opt in to a bounded transport check:

```sh
uv run python -m atlas_lyme_mcp.research_workflow --capacity-recovery-only --source-sha <verified-deployed-sha> --output <separate-recovery-directory>
```

This checks one indicator page (page_size 1), at most twice per host, with the
same arguments and a separate request ID/attempt number. A retry occurs only after
a retryable RATE_LIMITED response with an integer Retry-After of 1-60 seconds;
the full delay plus 0-0.25 seconds jitter is honored. Longer/invalid delays are
reported without a retry, never shortened. A second failure ends that check.
Each host is bounded to 125 seconds including connection setup; timed-out or
cancelled attempts retain their recorded outcomes. The existing 60-second pause
between aliases remains. At most four upstream requests per host are generated.
First-attempt success explicitly does not prove recovery; first-attempt failures
remain visible even when the second succeeds. These receipts are labeled
`capacity_recovery_check` and do not certify the cited Pennsylvania workflow or
resolve a missing public provenance resource. Service limits do not change.

The locked SDK converts the middleware's plain-JSON HTTP 429 into a generic
JSON-RPC internal error, discarding HTTP status and Retry-After. The harness
therefore observes response headers before SDK conversion, correlated to the
current POST and its exact request ID. It does not read or copy the rejection
body. A missing/invalid Retry-After stays unknown and prevents a retry; the
harness never infers a delay from the generic SDK error. Offline integration
tests use the actual locked Client/Streamable HTTP transport with successful
initialization and tool discovery followed by a mocked plain-JSON HTTP 429.

Each host is bounded to three indicator pages, three measure continuations, eight
provenance references, two profiles and the fixed comparison/scores/model calls:
at most 49 downstream requests. A continuation/reference beyond that bound fails
explicitly rather than claiming completeness. The checker pauses 60 seconds after
the first host to respect shared instance quotas across aliases. Existing callers
can still cause capacity rejection; record it as a failed check, not an outage or
absence. The manual GitHub workflow has a ten-minute job timeout and seven-day
artifact retention; no cron/schedule is enabled, and it needs no Atlas credentials.

Do not close #45 or other incident tickets based only on unit tests, green CI,
health, logs or this checker's implementation. Record exact deployed SHA and
both-host real-client receipts, inspect the cited response against the prompt,
and preserve unresolved runtime/source prerequisites. Source admission, new
monitoring spend, automatic alert routing and scheduled monitoring require their
own necessary authorization. Roll back through the existing source release flow.
