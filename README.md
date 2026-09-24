# One Health Lyme Gap Atlas MCP

An agent-facing Model Context Protocol server for Atlas. This foundation exposes one operational `server_status` tool; it contains no Lyme data or risk logic. Future domain tools should call approved Atlas APIs/services, leaving business rules and governed persistence in their owning repositories.

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

This client connects by Streamable HTTP, lists tools, and calls `server_status`. MCP Inspector can also connect to `http://127.0.0.1:8000/mcp` using its Streamable HTTP transport. This service currently documents HTTP operation; no stdio entry point is configured.

## Container

```sh
docker build -t atlas-lyme-mcp:local .
docker run --rm --name atlas-lyme-mcp -p 8000:8000 atlas-lyme-mcp:local
```

In another shell, check `http://127.0.0.1:8000/healthz`, run the client command above, then inspect `docker logs atlas-lyme-mcp`. Alternatively run `docker compose up --build` and `docker compose down`. The image runs as a non-root user and includes a `/healthz` health check.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | ASGI bind address |
| `PORT` | `8000` | Listening port, 1–65535 |
| `MCP_ALLOWED_HOSTS` | unset | Comma-separated exact Host header allowlist for a later deployment |

The official SDK protects localhost by default. A real DigitalOcean hostname will need `MCP_ALLOWED_HOSTS` set to its accepted Host values, with a separately reviewed TLS proxy and authentication design. `/healthz` is intentionally unauthenticated and returns only status. `.env.example` contains non-secret examples; `uv run` does not automatically load it. No DigitalOcean deployment is part of this foundation.

## Verification

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
docker build -t atlas-lyme-mcp:local .
```

After the build, run the container and check both endpoints plus `server_status` as above. CI runs these quality commands and the Docker build without Atlas or production credentials.
