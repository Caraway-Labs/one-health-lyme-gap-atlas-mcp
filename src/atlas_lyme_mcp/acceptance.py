"""Opt-in real public API/MCP evidence fidelity receipt; never used by offline CI."""

import asyncio
import json
import os
from typing import Any

from mcp import Client

from atlas_lyme_mcp.application.client import AtlasClient


async def verify() -> None:
    url = os.environ["MCP_URL"]
    if url not in {
        "https://mcp.onehealthatlas.org/mcp",
        "https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp",
    }:
        raise ValueError("Acceptance requires an approved existing public MCP endpoint")
    api = AtlasClient("https://api.onehealthatlas.org")
    async with Client(url, mode="legacy") as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == {
            "server_status",
            "atlas_smoke_test",
            "atlas_discover_indicators",
            "atlas_get_county_profile",
            "atlas_get_evidence_provenance",
        }
        receipts: dict[str, Any] = {
            "endpoint": url,
            "protocol": client.protocol_version,
            "tools": sorted(names),
        }
        for name in ("server_status", "atlas_smoke_test"):
            result = await client.call_tool(name, {})
            assert not result.is_error
            receipts[name] = result.structured_content
        discovery = await client.call_tool(
            "atlas_discover_indicators", {"indicator_id": "human_disease_burden", "page_size": 1}
        )
        assert not discovery.is_error and discovery.structured_content
        assert discovery.structured_content["indicators"]
        assert discovery.structured_content["measures"]
        receipts["discovery"] = discovery.structured_content
        cases: dict[str, dict[str, str | int]] = {
            "01001": {"measure_id": "case_count_floor_2023", "year": 2023},
            "19135": {
                "measure_id": "burgdorferi_status",
                "start_date": "2025-12-31",
                "end_date": "2025-12-31",
            },
        }
        for county, selection in cases.items():
            arguments = {"county_fips": county, "selections": [selection]}
            profile = await client.call_tool("atlas_get_county_profile", arguments)
            assert not profile.is_error and profile.structured_content
            data = profile.structured_content["selections"][0]["observations"]
            assert data
            direct = await api.get(
                "observations",
                selection | {"geography_type": "county", "geography_id": county, "page_size": 31},
                "CollectionEnvelope_Observation_",
            )
            assert data == direct["data"], "MCP/API evidence mismatch"
            assert profile.structured_content["meta"]["release_id"] == data[0]["release_id"]
            assert data[0]["limitations"] and data[0]["evidence"]
            if county == "01001":
                assert data[0]["value_state"] == "MISSING" and data[0]["value"] is None
            else:
                assert data[0]["value_state"] == "OBSERVED" and data[0]["value"] == "Present"
                assert data[0]["temporal_grain"] == "CUMULATIVE"
            receipts[f"profile_{county}"] = profile.structured_content
        observation = receipts["profile_19135"]["selections"][0]["observations"][0]
        provenance = await client.call_tool(
            "atlas_get_evidence_provenance",
            {
                "reference_type": "source",
                "reference_id": observation["source_id"],
                "expected_release_id": observation["release_id"],
            },
        )
        assert not provenance.is_error and provenance.structured_content
        source = await api.get(
            "sources", None, "ResourceEnvelope_Source_", observation["source_id"]
        )
        assert provenance.structured_content["resource"] == source["data"]
        receipts["provenance"] = provenance.structured_content
        failure = await client.call_tool(
            "atlas_get_evidence_provenance",
            {
                "reference_type": "source",
                "reference_id": observation["source_id"],
                "expected_release_id": "unsupported-historical-release",
            },
        )
        assert failure.is_error and failure.structured_content
        assert failure.structured_content["code"] == "RELEASE_CHANGED"
        receipts["safe_failure"] = failure.structured_content
        print(json.dumps(receipts, indent=2))


if __name__ == "__main__":
    asyncio.run(verify())
