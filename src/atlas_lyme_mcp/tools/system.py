"""Bounded operational MCP capabilities."""

from atlas_lyme_mcp import __version__


def server_status() -> dict[str, str]:
    """Return public operational metadata about this MCP service."""
    return {"service": "atlas-lyme-mcp", "version": __version__, "status": "ok"}
