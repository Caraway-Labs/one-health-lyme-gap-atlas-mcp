# DigitalOcean MCP development deployment

This runbook retains historical Epic #4 receipts and the existing release procedure.
MCP #27 supersedes the operational inventory: exactly nine domain tools are
exposed. `server_status` and `atlas_smoke_test` are intentionally removed, a
backward-incompatible change for their callers; the SDK returns unknown-tool
errors without aliases. Historical ADRs and receipts below describe past releases. ADR 0003 authorizes the original evidence tools; proposed ADR 0005 covers the five research additions and requires owner review; see [the current contract](../public-evidence-tools.md). Database connections, private APIs, inference and writes remain excluded. Use both branded and starter HTTPS endpoints.

## Architecture and configuration

App Platform builds the repository `Dockerfile` from reviewed `main` with automatic source deployment disabled. One `mcp` web service in `sfo` listens on `0.0.0.0:8000` and has an HTTP health check at `/healthz`. Streamable HTTP is at `/mcp`; it uses stateless JSON responses. The spec is `.do/app.yaml` and the governance record is `docs/adr/0001-mcp-development-app-platform.md`.

| Variable | Value | Reason |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Accept App Platform ingress inside the container |
| `PORT` | `8000` | Match Dockerfile and `http_port` |
| `MCP_ALLOWED_HOSTS` | `oh-lyme-mcp-dev-7jcfi.ondigitalocean.app,oh-lyme-mcp-dev-7jcfi.ondigitalocean.app:443,mcp.onehealthatlas.org,mcp.onehealthatlas.org:443` | Exact starter and branded Hosts, with optional HTTPS port; no wildcards |

Keep the starter hostname explicit so a change to DigitalOcean's primary domain cannot remove its Host allowance. Do not commit a token, add wildcard Hosts, disable SDK transport protection, or assume the server URL is a client's `Origin`. Requests with no `Origin` are valid. If an actual client receives HTTP 403, inspect the request's Origin and runtime log, confirm it is expected, then add only that exact Origin through a reviewed code/configuration change and tests. `/healthz` may work when `/mcp` fails Host validation, so check both.

## Branded hostname rollout (Web #356)

The owner approved publication of this existing smoke-test service on 2026-10-10.
Add `mcp.onehealthatlas.org` to the existing app, retaining its starter ingress
and routing. DigitalOcean's validator promotes the first custom domain from
ALIAS to PRIMARY; this does not configure a starter-domain redirect. Always
patch the full live spec rather than replace it with the repository template.

The owner enters a Squarespace CNAME: name `mcp`, data
`oh-lyme-mcp-dev-7jcfi.ondigitalocean.app`, with no scheme or path. Confirm
DigitalOcean's live alias before entry and review the owner's screenshot before
Save. DNS/TLS completion remains pending until independently verified.

After Save, inspect authoritative/public DNS, DigitalOcean domain validation,
and a hostname-valid managed certificate. Run `/healthz` and the official SDK
check client on both hosts; verify exactly nine domain tools, advertised schemas, retired-name rejection
and a successful structured county-resolution result. Test unexpected Hosts and ports remain rejected. Compare live spec
against its pre-change snapshot: only domains and `MCP_ALLOWED_HOSTS` may differ.
Record deployment ID/SHA, results and logs in Web #356; close it only after all
checks pass, leaving #353 open. Owner review is required before merging this PR.

## Local preflight

Use Python 3.12, `uv`, Docker, authenticated `doctl`, and `gh`. From this repository:

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
doctl apps spec validate .do/app.yaml
docker build -t atlas-lyme-mcp:local .
docker run --rm --name atlas-lyme-mcp -p 8000:8000 atlas-lyme-mcp:local
```

In another shell, run `curl.exe --fail --show-error http://127.0.0.1:8000/healthz`, then `uv run python -m atlas_lyme_mcp.check_client`. The client initializes MCP, discovers exactly nine domain tools, validates schemas, rejects retired names, invokes county resolution and validates structured/text parity, then checks `/healthz`. It requires live publisher access. For offline checks use `uv run python tests/offline_server.py` as the server, as in protocol tests; hosted Docker CI mounts this test-only runner into the image. Inspect `docker logs atlas-lyme-mcp`; stop the container when done. `docker compose up --build` is an alternative local runner.

## Controlled GitHub release

Start from clean current `origin/main`, implement on a feature branch, and open a PR. Inspect its complete diff, tool surface, spec, ADR, runbook, secrets, and CI. Require green lint/format/type/tests/Docker build and review before merge. Synchronize local `main` and record the exact merged commit SHA. Deploy that SHA from `main` only.

## Inspect and create

Recheck live state before creation; do not reuse IDs from an old runbook. Confirm that the DigitalOcean GitHub integration can access `Caraway-Labs/one-health-lyme-gap-atlas-mcp`. If it cannot, stop rather than switch to a registry. Find the existing **TopX Lyme Challenge** project and check for an existing MCP app:

```powershell
doctl account get
doctl projects list
doctl projects resources list <project-id>
doctl apps list
doctl apps spec validate .do/app.yaml
```

If no MCP app exists, create one from the reviewed spec. Creation starts the first deployment; do not trigger another one:

```powershell
doctl apps create --spec .do/app.yaml --wait
doctl apps get <app-id> -o json
doctl projects resources assign <project-id> --resource do:app:<app-id>
doctl projects resources list <project-id>
doctl apps list-deployments <app-id> -o json
doctl apps get-deployment <app-id> <deployment-id> -o json
```

Confirm the project assignment, `main` source branch, exact reviewed source commit, active phase, generated `default_ingress` HTTPS URL, expected non-secret runtime variables, and health. If the source SHA differs from reviewed `main`, stop and correct provenance before acceptance testing.

## Remote verification and evidence

`tests/verify_release_catalog.py` compares raw remote metadata with both the
reviewed nine-entry baseline and the full local serialized catalog, including
descriptions and annotations. Run it from the exact reviewed merge checkout.

Set the hostname from the active app's `default_ingress`. Keep the URL, SHA, deployment ID, date, and non-secret results in the final evidence record. Do not copy credentials, full environment dumps, or sensitive infrastructure details.

```powershell
curl.exe --fail --show-error --silent https://<generated-host>/healthz
$env:MCP_URL = "https://<generated-host>/mcp"
uv run python -m atlas_lyme_mcp.check_client
uv run python tests/verify_release_catalog.py
uv run python -m atlas_lyme_mcp.acceptance
uv run python -m atlas_lyme_mcp.research_acceptance
doctl apps logs <app-id> mcp --type build
doctl apps logs <app-id> mcp --type run
```

Verify TLS certificate validity, HTTP health, MCP initialization, exactly nine domain tools, schemas, both retired-name rejections and successful structured county resolution on both public hosts. Run `uv run python -m atlas_lyme_mcp.acceptance` separately on each host for ADR 0003 scientific fidelity, missingness, provenance and safe failure. API #246 remains an upstream cumulative-evidence blocker: record the exact failing request and preserve the issue branch/worktree if full acceptance fails. Do not weaken assertions or claim scientific acceptance from identity verification. Review logs after the calls for startup failures, HTTP 421/403, redirects, transport failures, and crash loops. App health alone is insufficient.

## Cursor proof

After remote SDK verification, add the following to the user-local `~/.cursor/mcp.json`, preserving any existing servers. Do not commit the user file or add headers/authentication:

```json
{
  "mcpServers": {
    "atlas-lyme-dev": {
      "url": "https://<generated-host>/mcp"
    }
  }
}
```

In Cursor, confirm exactly nine domain tools appear. Call `atlas_resolve_geographies` with `{"geographies":[{"county_fips":"01001"}]}`. Expand the **actual MCP tool-call result** and capture the structured county identity and reference provenance. Correlate the call time with DigitalOcean run logs. Cursor's conversational summary does not prove remote invocation. Inspect Cursor's MCP Logs panel if connection or discovery fails.

## Historical Epic #4 UAT evidence (retired tools; not current instructions)

On 2026-09-26, the user completed Cursor UAT against the configured `atlas-lyme-dev` server at `https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp`. Cursor reported the MCP namespace as `ready`. The recorded local clock after both calls was 17:12:28 MDT (23:12:28 UTC). The UAT record places `server_status` before 17:11:07 MDT and `atlas_smoke_test` after 17:11:07 MDT but before 17:12:28 MDT; it does not contain exact per-call timestamps.

The UAT report's Cursor version sources disagreed: `cursor --version` and the installed package metadata reported 3.20.10, while two Windows uninstall registry entries reported 0.45.14 and 3.22.7. The report could not establish which registry entry belonged to the running Cursor process, so the running version is recorded as ambiguous.

The expanded MCP tool-call results were:

`server_status`:

```json
{
  "service": "atlas-lyme-mcp",
  "version": "0.1.0",
  "status": "ok"
}
```

`atlas_smoke_test`:

```json
{
  "service": "atlas-lyme-mcp",
  "version": "0.1.0",
  "status": "ok",
  "message": "Atlas MCP is alive on DigitalOcean. The ticks have been notified and are pretending this was all part of the plan."
}
```

The user-supplied report confirms both calls returned without invocation errors, all four smoke fields were present, the exact message matched, and Cursor did not switch servers. It also displayed an additional `mcp_auth` discovery entry, which was not invoked. Independent official-SDK discovery against the live endpoint returned only `atlas_smoke_test` and `server_status`; `mcp_auth` is not advertised by the Atlas MCP server.

DigitalOcean run logs show successful `/mcp` HTTP activity at 2026-09-26 23:11:15Z and 23:12:02Z (17:11:15 and 17:12:02 MDT), overlapping the reported smoke-call interval. The access logs record request paths and HTTP statuses, not MCP tool names, and the UAT report does not timestamp each tool result exactly; therefore they corroborate remote MCP traffic during UAT but cannot attribute an individual log line to a named tool. No 421 or 403 responses, transport errors, crashes, or startup failures appeared in the inspected recent log window.

After the UAT, the repository's official Python MCP SDK check client was run against the same URL. It initialized successfully, listed exactly `atlas_smoke_test` and `server_status`, invoked both, and asserted the expected structured values and exact smoke message. A fresh HTTPS health request returned HTTP 200 with successful TLS certificate verification. App Platform remained `ACTIVE` on source commit `8c2d3ecde0b875056a8486feea44a80050a02d8e`.

## Troubleshooting and redeployment

- `/healthz` succeeds but `/mcp` returns 421: inspect the public Host and resolved `MCP_ALLOWED_HOSTS`; allowlist only observed expected forms.
- `/mcp` returns 403: inspect the actual Origin. Add a precise Origin only after confirming it is expected and testing a reviewed change.
- HTTPS redirects to HTTP: use exact `/mcp`, inspect `Location` and proxy forwarding behavior, and correct only the verified proxy issue.
- Build/startup fails: inspect `doctl apps logs <app-id> mcp --type build` and `--type run`, plus deployment phase and source SHA.
- Cursor fails but the SDK succeeds: inspect Cursor MCP Logs and its configured URL before changing the server.

For a reviewed source or spec update, use `doctl apps update <app-id> --spec .do/app.yaml --update-sources --wait` and reverify the source SHA and both endpoints. For a controlled redeployment without a spec change, use `doctl apps create-deployment <app-id> --wait` and repeat the checks. Roll back by restoring a previously reviewed working source/spec, deploying it, and rerunning remote verification. Do not silently expose an unreviewed commit.

## Eventual removal

Leave the development app available after this epic. When its owner separately authorizes removal, first preserve the evidence and confirm the exact app ID and project; then use the App Platform delete command and verify the app and project resource listing. Removal is not part of Epic #4 completion.
