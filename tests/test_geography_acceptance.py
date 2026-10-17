"""Exercise the release script itself against the real SDK and controlled reference."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp import Client
from mcp_types import ListToolsResult
from test_geographies import resolver

from atlas_lyme_mcp import geography_acceptance
from atlas_lyme_mcp.check_client import EXPECTED_TOOLS
from atlas_lyme_mcp.server import create_server


@pytest.mark.parametrize("inventory", ["approved", "retired", "missing", "renamed", "duplicate"])
def test_geography_release_acceptance_inventory(
    inventory: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MCP_URL", "http://offline.invalid/mcp")
    with patch("atlas_lyme_mcp.server.GeographyResolver", resolver):
        server = create_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    if inventory == "retired":
        tools += [
            tools[0].model_copy(update={"name": name})
            for name in ("server_status", "atlas_smoke_test")
        ]
    elif inventory == "missing":
        tools.pop()
    elif inventory == "renamed":
        tools[0] = tools[0].model_copy(update={"name": "unexpected_tool"})
    elif inventory == "duplicate":
        tools.append(tools[0])
    client = Client(server, mode="legacy")
    with (
        patch.object(geography_acceptance, "GeographyResolver", resolver),
        patch.object(geography_acceptance, "Client", return_value=client),
        patch.object(client, "list_tools", AsyncMock(return_value=ListToolsResult(tools=tools))),
    ):
        if inventory == "approved":
            asyncio.run(geography_acceptance.verify())
            receipt = json.loads(capsys.readouterr().out)
            assert set(receipt["tools"]) == EXPECTED_TOOLS
            assert receipt["invalid_rejected"] is True
            assert len(receipt["four_input"]["results"]) == 4
        else:
            # SDK context managers preserve the failed assertion in an exception group.
            with pytest.raises(ExceptionGroup) as failure:
                asyncio.run(geography_acceptance.verify())

            def assertions(error: BaseException) -> list[BaseException]:
                if isinstance(error, BaseExceptionGroup):
                    return [leaf for child in error.exceptions for leaf in assertions(child)]
                return [error]

            assert any(isinstance(error, AssertionError) for error in assertions(failure.value))
