"""Opt-in real SDK identity acceptance; source-backed, never an offline fixture claim."""

import asyncio
import json
import os

from mcp import Client

from atlas_lyme_mcp.application.geographies import GeographyResolver
from atlas_lyme_mcp.check_client import EXPECTED_TOOLS
from atlas_lyme_mcp.tools.geography_contracts import GeographyArguments


async def verify() -> None:
    url = os.environ["MCP_URL"]
    arguments = {
        "geographies": [
            {"county": "Ada", "state": "Idaho"},
            {"county": "Valley", "state": "ID"},
            {"county_fips": "01001"},
            {"county": "Does not exist", "state": "ID"},
        ]
    }
    direct = await GeographyResolver().resolve(GeographyArguments.model_validate(arguments))
    assert direct.reference is not None
    async with Client(url, mode="legacy") as client:
        names = sorted(tool.name for tool in (await client.list_tools()).tools)
        assert len(names) == len(EXPECTED_TOOLS) and set(names) == EXPECTED_TOOLS
        single = await client.call_tool(
            "atlas_resolve_geographies", {"geographies": [{"county_fips": "16001"}]}
        )
        assert not single.is_error and single.structured_content
        assert single.structured_content["results"][0]["geography"]["county_fips"] == "16001"
        batch = await client.call_tool("atlas_resolve_geographies", arguments)
        assert not batch.is_error and batch.structured_content
        entries = batch.structured_content["results"]
        assert [r["status"] for r in entries] == ["resolved", "resolved", "resolved", "not_found"]
        assert [r["input_index"] for r in entries] == [0, 1, 2, 3]
        assert [r["geography"]["county_fips"] for r in entries[:3]] == ["16001", "16085", "01001"]
        assert [r["geography"] for r in entries] == [
            r.geography.model_dump() if r.geography else None for r in direct.results
        ]
        assert batch.structured_content["reference"]["sha256"] == direct.reference.sha256
        pair = await client.call_tool(
            "atlas_resolve_geographies", {"geographies": arguments["geographies"][:2]}
        )
        assert not pair.is_error and pair.structured_content
        invalid = await client.call_tool("atlas_resolve_geographies", {"geographies": []})
        assert invalid.is_error
        print(
            json.dumps(
                {
                    "endpoint": url,
                    "protocol": client.protocol_version,
                    "tools": names,
                    "single": single.structured_content,
                    "four_input": batch.structured_content,
                    "ada_valley": pair.structured_content,
                    "invalid_rejected": invalid.is_error,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(verify())
