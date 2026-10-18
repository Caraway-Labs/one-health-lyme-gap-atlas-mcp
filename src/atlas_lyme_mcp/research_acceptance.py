"""Opt-in official-SDK research/API parity checks; never part of offline CI."""

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from mcp import Client

from atlas_lyme_mcp.application.client import AtlasClient
from atlas_lyme_mcp.check_client import verify_client, verify_health


def without_response_time(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "response_at"}


async def verify() -> None:
    url = os.environ["MCP_URL"]
    parsed = urlsplit(url)
    if url not in {
        "https://mcp.onehealthatlas.org/mcp",
        "https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp",
    } and not (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.path == "/mcp"
        and parsed.port
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        raise ValueError("Use an approved public MCP host or explicit local loopback port")
    api = AtlasClient("https://api.onehealthatlas.org")
    selection: dict[str, str | int] = {"measure_id": "case_count_floor_2023", "year": 2023}
    cases: dict[str, dict[str, Any]] = {
        "atlas_compare_counties": {"county_fips": ["01001", "01003"], "selections": [selection]},
        "atlas_get_surveillance_priority": {"county_fips": ["09110"]},
        "atlas_get_atlas_scores": {"county_fips": ["09110"]},
        "atlas_review_state": {"state": "CT"},
        "atlas_build_evidence_brief": {"county_fips": "01001", "selections": [selection]},
    }
    receipt: dict[str, Any] = {"endpoint": url, "tools": {}}
    async with Client(url, mode="legacy") as client:
        await verify_client(client)
        receipt["protocol"] = client.protocol_version
        schemas = {tool.name: tool.output_schema for tool in (await client.list_tools()).tools}
        for name, args in cases.items():
            result = await client.call_tool(name, args)
            assert not result.is_error and result.structured_content is not None, (name, result)
            value = result.structured_content
            schema = schemas[name]
            assert schema is not None
            Draft202012Validator(schema).validate(value)
            assert result.content[0].type == "text"
            assert json.loads(result.content[0].text) == value
            if name == "atlas_compare_counties":
                for row in value["matrix"][0]["counties"]:
                    direct = await api.get(
                        "observations",
                        selection
                        | {
                            "geography_type": "county",
                            "geography_id": row["county_fips"],
                            "page_size": 31,
                        },
                        "CollectionEnvelope_Observation_",
                    )
                    assert row["observations"] == direct["data"]
                    assert without_response_time(row["availability"]) == without_response_time(
                        direct["meta"]
                    )
            elif name == "atlas_get_surveillance_priority":
                direct = await api.get(
                    "priority_availability",
                    None,
                    "research:Tier1CountyPriorityAvailability",
                    "09110",
                )
                assert value["counties"][0]["availability"] == direct
            elif name == "atlas_get_atlas_scores":
                metadata = await api.get("atlas_metadata", None, "research:AtlasMetadata")
                direct = await api.get(
                    "county_detail",
                    {"dataset_version": metadata["release_id"]},
                    "research:CountyDetail",
                    "09110",
                )
                assert value["metadata"] == metadata and value["counties"] == [direct]
            elif name == "atlas_review_state":
                direct = await api.get("state_review", None, "research:StateReview", "CT")
                assert {k: v for k, v in value["review"].items() if k != "evaluated_at"} == {
                    k: v for k, v in direct.items() if k != "evaluated_at"
                }
                assert value["review"]["result_state"] == "unsupported"
            else:
                direct = await api.get(
                    "observations",
                    selection
                    | {"geography_type": "county", "geography_id": "01001", "page_size": 31},
                    "CollectionEnvelope_Observation_",
                )
                assert value["evidence"]["selections"][0]["observations"] == direct["data"]
                assert value["reference_ids"] == [o["evidence"] for o in direct["data"]]
                for reference in value["resources"]:
                    resource = (
                        "sources" if reference["reference_type"] == "source" else "methodologies"
                    )
                    contract = (
                        "ResourceEnvelope_Source_"
                        if resource == "sources"
                        else "ResourceEnvelope_Methodology_"
                    )
                    resolved = await api.get(resource, None, contract, reference["reference_id"])
                    assert reference["resource"] == resolved["data"]
            receipt["tools"][name] = {"arguments": args, "api_parity": True, "result": value}
    verify_health(url)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    asyncio.run(verify())
