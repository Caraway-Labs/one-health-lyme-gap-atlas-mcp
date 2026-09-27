"""MCP-facing adapters for bounded operational capabilities."""

from atlas_lyme_mcp.application.operations import SMOKE_MESSAGE as SMOKE_MESSAGE
from atlas_lyme_mcp.application.operations import (
    operational_smoke,
    operational_status,
)


def server_status() -> dict[str, str]:
    """Return public operational metadata about this MCP service."""
    return operational_status()


def atlas_smoke_test() -> dict[str, str]:
    """Return a deterministic, data-free remote invocation proof."""
    return operational_smoke()
