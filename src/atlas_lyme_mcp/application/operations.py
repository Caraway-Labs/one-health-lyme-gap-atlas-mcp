"""Data-free operational responses assembled independently of MCP transport."""

from atlas_lyme_mcp import __version__

SMOKE_MESSAGE = (
    "Atlas MCP is alive on DigitalOcean. The ticks have been notified and are "
    "pretending this was all part of the plan."
)


def operational_status() -> dict[str, str]:
    """Return bounded public service metadata."""
    return {"service": "atlas-lyme-mcp", "version": __version__, "status": "ok"}


def operational_smoke() -> dict[str, str]:
    """Return the deterministic remote invocation proof."""
    return {**operational_status(), "message": SMOKE_MESSAGE}
