"""Official SDK check: protocol, nine contracts, domain execution and HTTP health."""

import asyncio
import json
import os
from urllib.request import urlopen

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.shared.exceptions import MCPError

EXPECTED_TOOLS = frozenset(
    {
        "atlas_discover_indicators",
        "atlas_get_county_profile",
        "atlas_get_evidence_provenance",
        "atlas_resolve_geographies",
        "atlas_compare_counties",
        "atlas_get_surveillance_priority",
        "atlas_get_atlas_scores",
        "atlas_review_state",
        "atlas_build_evidence_brief",
    }
)
RETIRED_TOOLS = ("server_status", "atlas_smoke_test")


async def verify_client(client: Client) -> dict[str, object]:
    """Check discovery and a bounded real identity operation; no diagnostic aliases."""
    if not client.protocol_version:
        raise RuntimeError("MCP initialization did not negotiate a protocol version")
    tools = (await client.list_tools()).tools
    names = [tool.name for tool in tools]
    if len(names) != 9 or set(names) != EXPECTED_TOOLS:
        raise RuntimeError(f"Unexpected tool list: {sorted(names)}")
    for tool in tools:
        Draft202012Validator.check_schema(tool.input_schema)
        assert tool.output_schema is not None
        Draft202012Validator.check_schema(tool.output_schema)
    for name in RETIRED_TOOLS:
        try:
            rejected = await client.call_tool(name, {})
        except MCPError as error:
            assert "Unknown tool" in str(error), str(error)
        else:
            assert rejected.is_error, f"Retired tool accepted: {name}"
            assert any(
                item.type == "text" and f"Unknown tool: {name}" in item.text
                for item in rejected.content
            ), rejected
    result = await client.call_tool(
        "atlas_resolve_geographies", {"geographies": [{"county_fips": "01001"}]}
    )
    assert not result.is_error and result.structured_content is not None
    schema = next(t.output_schema for t in tools if t.name == "atlas_resolve_geographies")
    assert schema is not None
    Draft202012Validator(schema).validate(result.structured_content)
    assert result.content[0].type == "text"
    assert json.loads(result.content[0].text) == result.structured_content
    item = result.structured_content["results"][0]
    assert item["status"] == "resolved", result.structured_content
    assert item["geography"]["county_fips"] == "01001"
    return dict(result.structured_content)


def verify_health(url: str) -> None:
    """Confirm the unchanged process-health response after MCP execution."""
    with urlopen(url.removesuffix("/mcp") + "/healthz", timeout=10) as response:
        assert response.status == 200
        assert json.load(response) == {"status": "ok"}


async def check() -> None:
    url = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
    async with Client(url, mode="legacy") as client:
        result = await verify_client(client)
        print(f"MCP initialized: {client.protocol_version}")
        print(f"Tools: {', '.join(sorted(EXPECTED_TOOLS))}")
        print(f"atlas_resolve_geographies: {result}")
    verify_health(url)


if __name__ == "__main__":
    asyncio.run(check())
