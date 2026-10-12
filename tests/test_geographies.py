"""Identity contract negatives and deterministic publisher-boundary behavior."""

import asyncio
import time
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import ValidationError

from atlas_lyme_mcp.application.geographies import SOURCE, VERSION, GeographyResolver
from atlas_lyme_mcp.tools.geographies import geography_tool
from atlas_lyme_mcp.tools.geography_contracts import Geography, GeographyArguments, Reference

ADA = Geography(
    county_fips="16001",
    county_name="Ada County",
    state_name="Idaho",
    state_abbreviation="ID",
    state_fips="16",
)
VALLEY = ADA.model_copy(update={"county_fips": "16085", "county_name": "Valley County"})
AUTAUGA = Geography(
    county_fips="01001",
    county_name="Autauga County",
    state_name="Alabama",
    state_abbreviation="AL",
    state_fips="01",
)
REF = Reference(
    source=SOURCE, version=VERSION, sha256="a" * 64, retrieved_at="2026-10-12T00:00:00Z"
)


def resolver() -> GeographyResolver:
    result = GeographyResolver()
    result.cached = ([ADA, VALLEY, AUTAUGA], REF)
    result.expires = time.monotonic() + 3600
    return result


def invoke(items: list[dict[str, Any]], source: GeographyResolver | None = None) -> dict[str, Any]:
    server = MCPServer("test", tools=[geography_tool(source or resolver())])
    response = asyncio.run(server.call_tool("atlas_resolve_geographies", {"geographies": items}))
    assert isinstance(response, CallToolResult) and not response.is_error
    assert response.structured_content is not None
    tool = asyncio.run(server.list_tools())[0]
    assert tool.output_schema is not None
    Draft202012Validator(tool.output_schema).validate(response.structured_content)
    return dict(response.structured_content)


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_sizes_order_and_duplicates(count: int) -> None:
    inputs = [{"county_fips": "01001"}] * count
    result = invoke(inputs)
    assert [r["input_index"] for r in result["results"]] == list(range(count))
    assert [r["requested"] for r in result["results"]] == inputs
    assert all(r["geography"]["county_fips"] == "01001" for r in result["results"])
    assert result["reference"] == REF.model_dump()


@pytest.mark.parametrize(
    "county,state", [("Ada", "Idaho"), ("ADA COUNTY", "id"), ("  Ada   County  ", "  IDAHO ")]
)
def test_name_normalization(county: str, state: str) -> None:
    result = invoke([{"county": county, "state": state}, {"county": "Valley", "state": "ID"}])
    assert [r["geography"]["county_fips"] for r in result["results"]] == ["16001", "16085"]


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"county_fips": "16001"}] * 5,
        [{"county_fips": "1001"}],
        [{"county_fips": 16001}],
        [{"county_fips": "１６００１"}],
        [{"county_fips": " 16001"}],
        [{"county_fips": "1600A"}],
        [{"county": "Ada"}],
        [{"county": "Ada", "state": ""}],
        [{"county": " ", "state": "ID"}],
        [{"county": "Ada\n", "state": "ID"}],
        [{"county_fips": "16001", "county": "Ada", "state": "ID"}],
        [{"county_fips": "16001", "state": None}],
        [{"county_fips": None}],
        [{"county": "Ada", "state": "ID", "geography_type": "city"}],
    ],
)
def test_invalid_input(items: list[dict[str, Any]]) -> None:
    with pytest.raises(SchemaError):
        Draft202012Validator(GeographyArguments.model_json_schema()).validate(
            {"geographies": items}
        )
    with pytest.raises(ValidationError):
        GeographyArguments.model_validate({"geographies": items})
    with pytest.raises(ToolError):
        invoke(items)


def test_overall_arguments_are_strict() -> None:
    with pytest.raises(ValidationError):
        GeographyArguments.model_validate(
            {"geographies": [{"county_fips": "16001"}], "url": SOURCE}
        )
    with pytest.raises(ValidationError):
        GeographyArguments.model_validate({"geographies": '[{"county_fips":"16001"}]'})


def test_official_sdk_discovery_and_invocation() -> None:
    async def check() -> None:
        server = MCPServer("test", tools=[geography_tool(resolver())])
        async with Client(server, mode="legacy") as client:
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == ["atlas_resolve_geographies"]
            result = await client.call_tool(
                "atlas_resolve_geographies",
                {
                    "geographies": [
                        {"county": "Ada", "state": "Idaho"},
                        {"county": "Valley", "state": "ID"},
                    ]
                },
            )
            assert not result.is_error and result.structured_content
            assert [
                r["geography"]["county_fips"] for r in result.structured_content["results"]
            ] == ["16001", "16085"]
            invalid = await client.call_tool("atlas_resolve_geographies", {"geographies": []})
            assert invalid.is_error

    asyncio.run(check())


def test_mixed_success_unknown_states_counties_fips() -> None:
    result = invoke(
        [
            {"county": "Ada", "state": "Idaho"},
            {"county": "Unknown", "state": "ID"},
            {"county": "Ada", "state": "Unknown"},
            {"county_fips": "00000"},
        ]
    )
    assert [r["status"] for r in result["results"]] == [
        "resolved",
        "not_found",
        "not_found",
        "not_found",
    ]
    assert all(r["geography"] is None for r in result["results"][1:])


def test_ambiguity_never_selects_first_candidate() -> None:
    source = resolver()
    duplicate_name = ADA.model_copy(update={"county_fips": "16999", "county_name": "Ada"})
    source.cached = ([ADA, VALLEY, duplicate_name], REF)
    result = invoke([{"county": "Ada", "state": "ID"}, {"county_fips": "16085"}], source)
    assert result["results"][0]["status"] == "ambiguous"
    assert result["results"][0]["geography"] is None
    assert len(result["results"][0]["candidates"]) == 2
    assert result["results"][1]["status"] == "resolved"


def test_county_equivalents_remain_distinct() -> None:
    source = resolver()
    source.cached = (
        [
            ADA.model_copy(update={"county_name": "Baltimore County"}),
            VALLEY.model_copy(update={"county_name": "Baltimore city"}),
        ],
        REF,
    )
    result = invoke(
        [{"county": "Baltimore", "state": "ID"}, {"county": "Baltimore city", "state": "ID"}],
        source,
    )
    assert [r["geography"]["county_fips"] for r in result["results"]] == ["16001", "16085"]


@pytest.mark.parametrize(
    "failure", ["http", "error", "invalid", "partial", "overflow", "redirect", "timeout"]
)
def test_reference_unavailability_and_no_stale_fallback(failure: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url).startswith(SOURCE + "/query?")
        assert request.url.params["where"] == "1=1"
        assert request.url.params["returnGeometry"] == "false"
        if failure == "timeout":
            raise httpx.ReadTimeout("private message")
        if failure == "http":
            return httpx.Response(503)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.org"})
        if failure == "error":
            return httpx.Response(200, json={"error": {"message": "private"}})
        if failure == "overflow":
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        if failure == "invalid":
            return httpx.Response(200, json={"features": [{"attributes": {"STCNTY": 16001}}]})
        return httpx.Response(200, json={"features": []})

    source = resolver()
    source.transport = httpx.MockTransport(handler)
    source.expires = 0
    result = invoke([{"county_fips": "16001"}, {"county": "Valley", "state": "ID"}], source)
    assert [r["status"] for r in result["results"]] == ["unavailable", "unavailable"]
    assert result["reference"] is None
    assert "private" not in str(result)
    invoke([{"county_fips": "16001"}], source)
    assert len(calls) == 1  # failure cooldown


@pytest.mark.parametrize("defect", [None, "duplicate", "state", "truncated", "continuation"])
def test_paged_reference_validation_digest_and_cache(defect: str | None) -> None:
    # Synthetic scope exercises the reader, not a maintained reference registry.
    rows = [
        {
            "attributes": {
                "STCNTY": f"{i % 51 + 1:02}{i // 51:03}",
                "STATE": f"Test State {i % 51 + 1}",
                "ST_ABBR": chr(65 + (i % 51) // 26) + chr(65 + (i % 51) % 26),
                "COUNTY": f"Test County {i}",
            }
        }
        for i in range(3144)
    ]
    if defect == "duplicate":
        rows[-1] = rows[0]
    if defect == "state":
        rows[-1]["attributes"]["STATE"] = "Conflicting State"
    if defect == "truncated":
        rows.pop()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["resultOffset"])
        calls.append(offset)
        return httpx.Response(
            200,
            json={
                "features": rows[offset : offset + 2000],
                "exceededTransferLimit": offset == 0 or defect == "continuation",
            },
        )

    source = GeographyResolver(httpx.MockTransport(handler))
    result = invoke([{"county_fips": "01000"}], source)
    if defect:
        assert result["results"][0]["status"] == "unavailable"
    else:
        assert result["results"][0]["status"] == "resolved"
        assert result["reference"]["version"] == VERSION
        assert len(result["reference"]["sha256"]) == 64
        assert invoke([{"county_fips": "01000"}], source)["reference"] == result["reference"]
    assert calls == [0, 2000]
