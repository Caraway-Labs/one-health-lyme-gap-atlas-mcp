"""Bounded operational MCP capabilities."""

from atlas_lyme_mcp import __version__

SMOKE_MESSAGE = (
    "Atlas MCP is alive on DigitalOcean. The ticks have been notified and are "
    "pretending this was all part of the plan."
)


def server_status() -> dict[str, str]:
    """Return public operational metadata about this MCP service."""
    return {"service": "atlas-lyme-mcp", "version": __version__, "status": "ok"}


def atlas_smoke_test() -> dict[str, str]:
    """Return a deterministic, data-free remote invocation proof."""
    return {
        "service": "atlas-lyme-mcp",
        "version": __version__,
        "status": "ok",
        "message": SMOKE_MESSAGE,
    }
