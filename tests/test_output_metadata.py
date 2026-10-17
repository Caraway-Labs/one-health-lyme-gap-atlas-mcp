"""MCP output prose, validation equivalence and canonical ownership regressions."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from catalog_discovery import discover_catalog
from metadata_gate import validate_catalog, without_input_descriptions

FIXTURES = Path(__file__).parent / "fixtures"
REVIEW = json.loads((FIXTURES / "output-schema-25-review.json").read_text())


def constraints(value: Any) -> Any:
    """Erase annotations and vacuous property declarations, never constraints."""
    value = without_input_descriptions(value)
    if isinstance(value, dict):
        result = {key: constraints(child) for key, child in value.items()}
        if "properties" in result:
            result["properties"] = {k: v for k, v in result["properties"].items() if v != {}}
            if not result["properties"]:
                del result["properties"]
        return result
    if isinstance(value, list):
        return [constraints(child) for child in value]
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def test_raw_output_constraints_and_scientific_bundle_unchanged() -> None:
    for tool in discover_catalog():
        receipt = REVIEW["tools"][tool["name"]]
        assert digest(constraints(tool.get("outputSchema"))) == receipt["before_constraints_sha256"]
    bundle = Path("src/atlas_lyme_mcp/contracts/public-api-schema.json").read_bytes()
    assert hashlib.sha256(bundle).hexdigest() == REVIEW["canonical_bundle_sha256"]


def test_serialized_output_descriptions() -> None:
    tools = {tool["name"]: tool["outputSchema"] for tool in discover_catalog()}
    for name in (
        "atlas_discover_indicators",
        "atlas_get_county_profile",
        "atlas_get_evidence_provenance",
    ):
        fields = tools[name]["properties"]
        assert all(len(field["description"].split()) >= 3 for field in fields.values())
        assert "null" in fields["meta"]["properties"]["release_id"]["description"]
    profile = tools["atlas_get_county_profile"]["properties"]["selections"]["items"]["properties"]
    assert all("description" in value for value in profile.values())
    assert "never zero disease incidence" in profile["retrieval_state"]["description"]
    geography = tools["atlas_resolve_geographies"]
    for model in ("GeographyResult", "Reference"):
        assert all(
            "description" in field for field in geography["$defs"][model]["properties"].values()
        )
    status = geography["$defs"]["GeographyResult"]["properties"]["status"]["description"]
    assert all(word in status for word in ("resolved", "ambiguous", "not_found", "unavailable"))
    assert "automatic" in status


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("type", "integer"),
        ("enum", ["other"]),
        ("required", ["new"]),
        ("maxItems", 1),
        ("$ref", "#/components/schemas/Source"),
    ],
)
def test_unrelated_output_drift_still_fails(keyword: str, value: Any) -> None:
    catalog = discover_catalog()
    tool = next(t for t in catalog if t["name"] == "atlas_get_county_profile")
    tool["outputSchema"]["properties"]["selections"][keyword] = value
    baseline = json.loads((FIXTURES / "mcp-catalog-contract.json").read_text())
    with pytest.raises(AssertionError, match="outputSchema"):
        validate_catalog(catalog, baseline)


@pytest.mark.parametrize("failure", [False, True])
def test_raw_http_success_and_error_parity(monkeypatch: pytest.MonkeyPatch, failure: bool) -> None:
    import httpx
    from starlette.testclient import TestClient
    from test_evidence_tools import PROFILE, RELEASE, fixture
    from test_geographies import resolver

    from atlas_lyme_mcp.application.client import AtlasClient
    from atlas_lyme_mcp.config import Settings
    from atlas_lyme_mcp.server import create_app

    def handler(request: httpx.Request) -> httpx.Response:
        if failure:
            return httpx.Response(503)
        resource = request.url.path.split("/")[2]
        names = {
            "indicators": "indicators",
            "measures": "measures",
            "observations": "observations",
            "sources": "source",
        }
        return httpx.Response(200, json=fixture(names[resource]))

    client = AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
    monkeypatch.setattr("atlas_lyme_mcp.server.AtlasClient", lambda _: client)
    monkeypatch.setattr("atlas_lyme_mcp.server.GeographyResolver", resolver)
    headers = {"Accept": "application/json, text/event-stream"}
    calls = {
        "atlas_discover_indicators": {},
        "atlas_get_county_profile": PROFILE,
        "atlas_get_evidence_provenance": {
            "reference_type": "source",
            "reference_id": "human",
            "expected_release_id": RELEASE,
        },
        "atlas_resolve_geographies": {"geographies": [{"county_fips": "01001"}]},
    }
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1:8000") as http:
        initialized = http.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "output-ci", "version": "1"},
                },
            },
        )
        initialized.raise_for_status()
        headers["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]
        for index, (name, arguments) in enumerate(calls.items(), 2):
            response = http.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            response.raise_for_status()
            result = response.json()["result"]
            assert result.get("isError", False) == (failure and name != "atlas_resolve_geographies")
            assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
            if failure and name != "atlas_resolve_geographies":
                assert result["structuredContent"]["code"] == "UPSTREAM_UNAVAILABLE"
