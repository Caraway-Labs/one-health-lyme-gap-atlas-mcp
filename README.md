# One Health Lyme Gap Atlas MCP

An agent-facing Model Context Protocol server for Atlas. The service exposes anonymous read-only indicator discovery, bounded county evidence profiles and source/methodology resolution, and county identity resolution. Strict FIPS validation executes shared-domain logic locally; governed retrieval crosses the approved public API boundary. No scoring, inference, database access or private API is available. See [the tool contract](docs/public-evidence-tools.md). REST and MCP are peer adapters: future tools may execute approved portable shared-domain logic locally and must call approved Atlas APIs/services when they need governed data or service-owned behavior. See [ADR 0002](docs/adr/0002-mcp-peer-adapter-boundaries.md) for the decision checklist.

The direct `one-health-lyme-gap-atlas-shared` dependency uses the portable base distribution at commit `83ccbe76047185f6aacaff551afd8b03d88aa5cf` (source version `1.0.0`), pinned in `pyproject.toml` and `uv.lock`. No `snowflake`, `observability`, or `legacy` extra is requested. Production imports are limited to `lyme_gap_atlas_shared.domain`; architecture tests guard this boundary.

The four domain tools use thin `tools/` adapters over independently testable `application/` functions. The [future-tool checklist](docs/future-tool-template.md) defines where shared pure logic and a future approved service client belong; the approved public-service client now supplies bounded evidence retrieval.

## Prerequisites and local setup

Install Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker for container use. From this repository:

```sh
uv sync --locked
uv run atlas-lyme-mcp
```

The process listens on `0.0.0.0:8000` by default. Streamable HTTP is at `http://127.0.0.1:8000/mcp`; the independent HTTP health route is `http://127.0.0.1:8000/healthz`. Stop the process with Ctrl+C. Importing `atlas_lyme_mcp.server` only defines constructors and never starts the listener.

To prove MCP discovery and invocation with the official Python SDK, leave the server running and run:

```sh
uv run python -m atlas_lyme_mcp.check_client
```

This client initializes Streamable HTTP, discovers exactly four domain tools, validates
all advertised schemas, confirms both retired tool names are rejected, invokes
`atlas_resolve_geographies` for county FIPS `01001`, validates structured output
and JSON text parity, and checks `/healthz` afterward. This default check uses the
live county publisher and requires network access. Set `MCP_URL=https://<host>/mcp`
to check a deployed instance. MCP Inspector can also connect to the endpoint.
No stdio entry point is configured.

The public inventory is exactly `atlas_resolve_geographies`,
`atlas_discover_indicators`, `atlas_get_county_profile`, and
`atlas_get_evidence_provenance`. MCP #27 intentionally removes `server_status`
and `atlas_smoke_test`: this is backward-incompatible for clients invoking those
names. They now receive the SDK's standard unknown-tool error, with no aliases.
Use `/healthz` for HTTP process health, MCP initialization and `tools/list` for
protocol/discovery, and a supported domain call for execution verification.

Offline protocol tests run the production app through `tests/offline_server.py`,
which supplies a controlled in-memory county reference without external I/O.
Docker CI mounts that test-only runner into the built image; the production image
and normal entry point contain no fixture switch. Full deployed scientific
acceptance remains `python -m atlas_lyme_mcp.acceptance` on both approved hosts;
the known API #246 cumulative-evidence blocker is not waived by an identity check.

## Container

```sh
docker build -t atlas-lyme-mcp:local .
docker run --rm --name atlas-lyme-mcp -p 8000:8000 atlas-lyme-mcp:local
```

In another shell, check `http://127.0.0.1:8000/healthz`, run the client command above, then inspect `docker logs atlas-lyme-mcp`. Alternatively run `docker compose up --build` and `docker compose down`. The image runs as a non-root user and includes a `/healthz` health check.

## Configuration

Web [#356](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-web/issues/356)
authorizes the additive hostname `https://mcp.onehealthatlas.org/mcp` for this
existing MCP service. Verify DNS and managed TLS during each release acceptance;
retain `https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp` throughout rollout.
This publication does not change the tools or authentication behavior.

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | ASGI bind address |
| `PORT` | `8000` | Listening port, 1–65535 |
| `MCP_ALLOWED_HOSTS` | unset | Comma-separated exact Host header allowlist for deployed `/mcp` traffic |

The official SDK protects localhost by default. The development App Platform spec allowlists its generated public hostname without disabling that protection. Requests without an `Origin` are valid; no Origin allowance or browser CORS is configured for this proof. `/healthz` is intentionally unauthenticated and returns only status. `.env.example` contains non-secret examples; `uv run` does not automatically load it. See the [DigitalOcean deployment runbook](docs/operations/digitalocean-mcp.md) and [deployment decision](docs/adr/0001-mcp-development-app-platform.md) for the reviewed public development deployment, remote checks, Cursor setup, logs, redeployment, and eventual cleanup.

## Verification

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
docker build -t atlas-lyme-mcp:local .
```

After the build, run the container and check both endpoints and domain invocation as above. CI runs these quality commands and the Docker build without Atlas or production credentials.


## County identity resolution

`atlas_resolve_geographies` resolves 1–4 county references by county/state name
or exact FIPS. See [the bounded identity contract](docs/geography-resolution.md)
and [ADR 0004](docs/adr/0004-bounded-county-reference-resolution.md). Identity
resolution does not establish Atlas observations or evidence adequacy.
