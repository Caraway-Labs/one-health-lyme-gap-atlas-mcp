"""Exercise the actual HTTP transport with the official MCP client."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from mcp import Client

from atlas_lyme_mcp.check_client import check


@pytest.fixture
def running_server() -> Iterator[int]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port), "MCP_ALLOWED_HOSTS": ""}
    process = subprocess.Popen(
        [sys.executable, "tests/offline_server.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("MCP server exited before becoming healthy")
            try:
                with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("MCP server did not become healthy")
        yield port
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def test_http_initialize_discover_and_invoke(
    running_server: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MCP_URL", f"http://127.0.0.1:{running_server}/mcp")
    asyncio.run(check())
    output = capsys.readouterr().out
    assert "MCP initialized:" in output
    assert "atlas_resolve_geographies:" in output
    assert "server_status" not in output
    assert "atlas_smoke_test" not in output


def test_http_discovery_input_descriptions(running_server: int) -> None:
    """Assert client-visible metadata, including referenced array item models."""

    async def discover() -> None:
        async with Client(f"http://127.0.0.1:{running_server}/mcp", mode="legacy") as client:
            response = await client.list_tools()
            tools = {tool.name: tool for tool in response.tools}
            assert set(tools) == {
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
            discovery = tools["atlas_discover_indicators"].input_schema["properties"]
            assert "published indicator ID" in discovery["indicator_id"]["description"]
            assert "defaults to 3" in discovery["page_size"]["description"]
            assert "meta.next_page_token" in discovery["page_token"]["description"]
            assert "meta.measure_page_tokens" in discovery["measure_page_token"]["description"]
            profile = tools["atlas_get_county_profile"].input_schema
            assert "leading zeros" in profile["properties"]["county_fips"]["description"]
            assert "unique" in profile["properties"]["selections"]["description"]
            selection_ref = profile["properties"]["selections"]["items"]["$ref"]
            selection = profile["$defs"][selection_ref.rsplit("/", 1)[1]]["properties"]
            assert "published measure ID" in selection["measure_id"]["description"]
            assert "never both" in selection["year"]["description"]
            assert "31 inclusive days" in selection["start_date"]["description"]
            assert "YYYY-MM-DD" in selection["end_date"]["description"]
            assert "same county_fips" in selection["page_token"]["description"]
            provenance = tools["atlas_get_evidence_provenance"].input_schema["properties"]
            assert "reference kind" in provenance["reference_type"]["description"]
            assert "source_id or methodology_id" in provenance["reference_id"]["description"]
            assert "RELEASE_CHANGED" in provenance["expected_release_id"]["description"]
            geography = tools["atlas_resolve_geographies"].input_schema
            assert "input order" in geography["properties"]["geographies"]["description"]
            geography_ref = geography["properties"]["geographies"]["items"]["$ref"]
            request = geography["$defs"][geography_ref.rsplit("/", 1)[1]]["properties"]
            assert "leading zeros" in request["county_fips"]["description"]
            assert "No fuzzy matching" in request["county"]["description"]
            assert "postal abbreviation" in request["state"]["description"]
            # Input descriptions must not leak into the shared requested output model.
            output = tools["atlas_resolve_geographies"].output_schema
            assert output is not None
            requested_output = output["$defs"]["GeographyRequest"]["properties"]
            assert all("description" not in field for field in requested_output.values())

    asyncio.run(discover())


def test_official_sdk_invokes_all_five_research_tools(running_server: int) -> None:
    async def invoke() -> None:
        import json

        from jsonschema import Draft202012Validator

        cases: dict[str, dict[str, Any]] = {
            "atlas_compare_counties": {
                "county_fips": ["01001", "01003"],
                "selections": [{"measure_id": "case_count_floor_2023", "year": 2023}],
            },
            "atlas_get_surveillance_priority": {"county_fips": ["09110"]},
            "atlas_get_atlas_scores": {"county_fips": ["09110"]},
            "atlas_review_state": {"state": "CT"},
            "atlas_build_evidence_brief": {
                "county_fips": "01001",
                "selections": [{"measure_id": "case_count_floor_2023", "year": 2023}],
            },
        }
        async with Client(f"http://127.0.0.1:{running_server}/mcp", mode="legacy") as client:
            schemas = {t.name: t.output_schema for t in (await client.list_tools()).tools}
            for name, args in cases.items():
                result = await client.call_tool(name, args)
                assert not result.is_error and result.structured_content is not None, result
                schema = schemas[name]
                assert schema is not None
                Draft202012Validator(schema).validate(result.structured_content)
                assert result.content[0].type == "text"
                assert json.loads(result.content[0].text) == result.structured_content

    asyncio.run(invoke())
