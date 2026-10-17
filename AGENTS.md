# MCP repository agent instructions

This repository owns the agent-facing MCP interface and orchestration for the One Health Lyme Gap Atlas. Its source of truth is this repository's code, tests, README, and the authoritative Atlas API/service contracts. Follow the parent workspace `AGENTS.md` and `TECHNOLOGY_AND_GOVERNANCE.md` where applicable.

- Use the official Python `mcp` SDK and Streamable HTTP at `/mcp`. Keep server construction importable and free of process startup side effects.
- REST and MCP are peer adapters over portable Atlas domain contracts. Use `lyme_gap_atlas_shared.domain` locally for stable, deterministic, infrastructure-independent logic; an unnecessary REST hop is not required. Cross genuine runtime or governed-data boundaries through an approved Atlas API/service.
- Keep tools semantic, task-oriented, and transport-focused. Application orchestration must not duplicate domain logic or become a second persistence backend. Do not import `lyme_gap_atlas_shared.infrastructure`, deprecated shared Snowflake shims, or hidden persistence packages; never access Snowflake or Neo4j directly. Follow [ADR 0002](docs/adr/0002-mcp-peer-adapter-boundaries.md) before adding a tool.
- Authentication, authorization, and real data-bearing capabilities require separate requirements and security review. An application/orchestration package alone does not imply a new deployed component.
- Do not add credentials, production URLs, secrets, or environment-specific identities to source, images, test fixtures, or logs. Use non-secret environment configuration; review any future authentication design separately.
- For documentation-only changes, run `git diff --check`, review instructions for consistency, and require applicable CI; local container execution and production redeployment are unnecessary unless an explicit repository policy requires them. For runtime changes, before completion run `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, `uv run pytest`, and `docker build -t atlas-lyme-mcp:local .`. Start the container and verify `/healthz`, MCP discovery/invocation, and container logs. Update tests and docs with changes.
- Keep the first service bounded to its status capability. Authentication, public deployment, production writes, and new domain capabilities need explicit requirements and review.

## Git Branching, Worktrees, and Delivery Lifecycle

### Start and isolate

- Before implementation, inspect `git status`, `git branch -vv`, and `git worktree list`; run `git fetch origin --prune` and record the resulting `origin/main` SHA. Never assume local `main` is current or modify the original checkout just to synchronize it.
- Give each independent issue one new feature branch, one dedicated Git worktree, and one PR. Use descriptive issue-specific names (branches prefixed `codex/`). Create the branch directly from freshly fetched `origin/main` with `git worktree add -b <branch> <path> origin/main`. If a branch or path exists, inspect it and choose a unique alternative; never reuse another session's resources.
- Perform all source edits, tests, commits, and PR preparation inside the issue worktree. Do not mix unrelated issues on a branch.

### Protect concurrent work

- Multiple sessions may run concurrently. Preserve the original checkout, other agents' directories and branches, and all unrelated uncommitted or unpushed work. Never discard changes to establish a clean starting point.
- Do not force-reset, force-delete, or overwrite Git state to resolve collisions. Report conflicts and preserve recoverable work when safe isolation is impossible. Use platform-neutral Git commands on Windows and Unix.

### Review, merge, and accept

- Open a PR targeting `main` and reference its issue. Review the complete diff and run applicable quality checks. Respect required reviews and branch protections; merge using the repository's established strategy only after required CI passes. Never bypass these controls. Record the exact merge SHA.
- When deployment is required, deploy the exact merged commit, verify the deployed SHA, execute applicable health and acceptance checks, and record deployment evidence in GitHub. Close the issue only after successful release acceptance. Documentation-only work needs no production redeployment unless an explicit repository policy requires it; close after merge and verification.
- If merge, deployment, or acceptance fails, preserve the feature branch and worktree for recovery and report the blocker.

### Clean up after acceptance

1. After merge and all applicable acceptance requirements succeed, verify the dedicated worktree has no uncommitted changes and the branch has no unpushed work requiring preservation. Confirm the PR contains the completed work before deleting anything.
2. From outside the dedicated worktree, run `git worktree remove <path>`, then `git branch -d <branch>`. Delete only that remote feature branch with `git push origin --delete <branch>` if it still exists and deletion is authorized.
3. Verify removal with `git worktree list`, `git branch --list <branch>`, and `git ls-remote --heads origin refs/heads/<branch>`. Confirm the original checkout and unrelated worktrees and branches remain unchanged.

Never use `--force`, `-D`, or manual directory deletion to bypass cleanup errors. If cleanup cannot safely finish, document the blocker and preserve recoverable work. Success does not require moving the original local `main` to the remote tip.

### Report completion

Include the starting `origin/main` SHA, feature branch, worktree path, PR URL, merge SHA, quality-check results, deployment evidence when applicable, issue status, local and remote branch cleanup status, worktree cleanup status, preservation of unrelated checkouts, and remaining blockers.
