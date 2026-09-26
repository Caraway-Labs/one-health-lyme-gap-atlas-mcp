# DigitalOcean MCP development deployment

This runbook covers Epic #4's public, unauthenticated **development smoke test**. The server exposes only `server_status` and `atlas_smoke_test`. It has no Atlas data or database connections, persistence, or write tools. Its public URL is an App Platform-generated HTTPS hostname. Authentication and production use require a separate decision.

## Architecture and configuration

App Platform builds the repository `Dockerfile` from reviewed `main` with automatic source deployment disabled. One `mcp` web service in `sfo` listens on `0.0.0.0:8000` and has an HTTP health check at `/healthz`. Streamable HTTP is at `/mcp`; it uses stateless JSON responses. The spec is `.do/app.yaml` and the governance record is `docs/adr/0001-mcp-development-app-platform.md`.

| Variable | Value | Reason |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Accept App Platform ingress inside the container |
| `PORT` | `8000` | Match Dockerfile and `http_port` |
| `MCP_ALLOWED_HOSTS` | `${APP_DOMAIN},${APP_DOMAIN}:*` | Allow only the generated public Host and its optional port form |

DigitalOcean expands `${APP_DOMAIN}` at runtime. Do not commit a token, add wildcard Hosts, disable SDK transport protection, or assume the server URL is a client's `Origin`. Requests with no `Origin` are valid. If an actual client receives HTTP 403, inspect the request's Origin and runtime log, confirm it is expected, then add only that exact Origin through a reviewed code/configuration change and tests. `/healthz` may work when `/mcp` fails Host validation, so check both.

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

In another shell, run `curl.exe --fail --show-error http://127.0.0.1:8000/healthz`, then `uv run python -m atlas_lyme_mcp.check_client`. The client explicitly initializes MCP, discovers both tools, invokes both, and asserts the exact structured smoke response. Inspect `docker logs atlas-lyme-mcp`; stop the container when done. `docker compose up --build` is an alternative local runner.

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

Set the hostname from the active app's `default_ingress`. Keep the URL, SHA, deployment ID, date, and non-secret results in the final evidence record. Do not copy credentials, full environment dumps, or sensitive infrastructure details.

```powershell
curl.exe --fail --show-error --silent https://<generated-host>/healthz
$env:MCP_URL = "https://<generated-host>/mcp"
uv run python -m atlas_lyme_mcp.check_client
doctl apps logs <app-id> mcp --type build
doctl apps logs <app-id> mcp --type run
```

Verify TLS certificate validity, HTTP health, MCP initialization, both discovered tools, both successful invocations, and the exact smoke message. Review logs after the calls for startup failures, HTTP 421/403, redirects, transport failures, and crash loops. App health alone is insufficient.

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

In Cursor, confirm the server is connected and both tools appear. Ask it to call `server_status`, then `atlas_smoke_test` with no arguments. Expand the **actual MCP tool-call result** and capture its four fields and exact message. Correlate the call time with DigitalOcean run logs. Cursor's conversational summary does not prove remote invocation. Inspect Cursor's MCP Logs panel if connection or discovery fails.

## Troubleshooting and redeployment

- `/healthz` succeeds but `/mcp` returns 421: inspect the public Host and resolved `MCP_ALLOWED_HOSTS`; allowlist only observed expected forms.
- `/mcp` returns 403: inspect the actual Origin. Add a precise Origin only after confirming it is expected and testing a reviewed change.
- HTTPS redirects to HTTP: use exact `/mcp`, inspect `Location` and proxy forwarding behavior, and correct only the verified proxy issue.
- Build/startup fails: inspect `doctl apps logs <app-id> mcp --type build` and `--type run`, plus deployment phase and source SHA.
- Cursor fails but the SDK succeeds: inspect Cursor MCP Logs and its configured URL before changing the server.

For a reviewed source or spec update, use `doctl apps update <app-id> --spec .do/app.yaml --update-sources --wait` and reverify the source SHA and both endpoints. For a controlled redeployment without a spec change, use `doctl apps create-deployment <app-id> --wait` and repeat the checks. Roll back by restoring a previously reviewed working source/spec, deploying it, and rerunning remote verification. Do not silently expose an unreviewed commit.

## Eventual removal

Leave the development app available after this epic. When its owner separately authorizes removal, first preserve the evidence and confirm the exact app ID and project; then use the App Platform delete command and verify the app and project resource listing. Removal is not part of Epic #4 completion.
