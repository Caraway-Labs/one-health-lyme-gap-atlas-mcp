"""Exercise in-process application behavior without MCP transport."""

from unittest.mock import patch

from atlas_lyme_mcp.application.operations import (
    SMOKE_MESSAGE,
    operational_smoke,
    operational_status,
)
from atlas_lyme_mcp.tools.system import atlas_smoke_test, server_status


def test_operational_application_is_independently_callable() -> None:
    status = operational_status()
    assert status == {"service": "atlas-lyme-mcp", "version": "0.1.0", "status": "ok"}
    assert operational_smoke() == {**status, "message": SMOKE_MESSAGE}


def test_mcp_tool_functions_delegate_to_application() -> None:
    with patch("atlas_lyme_mcp.tools.system.operational_status", return_value={"proof": "status"}):
        assert server_status() == {"proof": "status"}
    with patch("atlas_lyme_mcp.tools.system.operational_smoke", return_value={"proof": "smoke"}):
        assert atlas_smoke_test() == {"proof": "smoke"}
