# MCP repository agent instructions

This repository owns the agent-facing MCP interface and orchestration for the One Health Lyme Gap Atlas. Its source of truth is this repository's code, tests, README, and the authoritative Atlas API/service contracts. Follow the parent workspace `AGENTS.md` and `TECHNOLOGY_AND_GOVERNANCE.md` where applicable.

- Use the official Python `mcp` SDK and Streamable HTTP at `/mcp`. Keep server construction importable and free of process startup side effects.
- Keep Atlas business logic and governed data processing in their owning API, data, knowledge graph, and machine learning services. New domain tools should normally call approved Atlas APIs/services. Never access Snowflake or Neo4j directly from this service without a recorded architecture decision.
- Do not add credentials, production URLs, secrets, or environment-specific identities to source, images, test fixtures, or logs. Use non-secret environment configuration; review any future authentication design separately.
- Work from current `origin/main` on a feature branch. Make a PR, review its diff and CI, and merge only after all required checks pass. End with local `main` synchronized and clean.
- Before completion run `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, `uv run pytest`, and `docker build -t atlas-lyme-mcp:local .`. Start the container and verify `/healthz`, MCP discovery/invocation, and container logs. Update tests and docs with changes.
- Keep the first service bounded to its status capability. Authentication, public deployment, production writes, and new domain capabilities need explicit requirements and review.
