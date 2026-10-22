"""Explicit API time selections preserve original context and cumulative evidence."""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp_types import CallToolResult
from pydantic import ValidationError

from atlas_lyme_mcp.application.client import AtlasClient
from atlas_lyme_mcp.server import create_server
from atlas_lyme_mcp.tools.contracts import CONTEXT_VINTAGES, Selection


def context_page(measure: str, vintage: int) -> dict[str, Any]:
    page: dict[str, Any] = json.loads(
        (Path(__file__).parent / "fixtures/public-observations.json").read_text()
    )
    row = page["data"][0]
    row.update(
        measure_id=measure,
        temporal_grain="PERIOD",
        period_start="2018-01-01",
        period_end="2022-12-31",
        value=1234,
        value_state="OBSERVED",
        unit="people",
        county_context={
            "contract_version": "atlas-county-context-consumer/1",
            "vintage_year": vintage,
            "source_field": "E_TOTPOP",
            "value_type": "integer",
            "category_label": None,
            "definition": "Synthetic transport fixture; not published county evidence.",
            "allowed_value_states": ["OBSERVED", "ZERO", "MISSING"],
            "metadata_methodology_version": "fixture-1",
        },
    )
    row["geography"]["geography_id"] = "42029"
    if measure == "rucc_2023":
        row.update(temporal_grain="VINTAGE_YEAR", period_start=None, period_end=None)
    return page


@pytest.mark.parametrize("measure,vintage", CONTEXT_VINTAGES.items())
def test_context_selection_schema_and_exact_query(measure: str, vintage: int) -> None:
    selection = {"measure_id": measure, "vintage_year": vintage}
    Draft202012Validator(Selection.model_json_schema()).validate(selection)
    page = context_page(measure, vintage)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert dict(request.url.params) == {
            "measure_id": measure,
            "vintage_year": str(vintage),
            "geography_type": "county",
            "geography_id": "42029",
            "page_size": "31",
        }
        return httpx.Response(200, json=page)

    server = create_server(
        client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
    )
    result = asyncio.run(
        server.call_tool(
            "atlas_get_county_profile", {"county_fips": "42029", "selections": [selection]}
        )
    )
    assert isinstance(result, CallToolResult)
    assert not result.is_error, result
    assert len(calls) == 1
    entry = result.structured_content["selections"][0]
    assert entry["request"] == selection
    assert entry["observations"] == page["data"]
    assert result.content[0].type == "text"
    assert json.loads(result.content[0].text) == result.structured_content


@pytest.mark.parametrize("measure", ["scapularis_status", "burgdorferi_status"])
def test_cumulative_selection_is_explicit_and_not_annual(measure: str) -> None:
    Selection(measure_id=measure, start_date="2025-12-31", end_date="2025-12-31")
    with pytest.raises(ValidationError, match="is cumulative; use start_date=end_date=2025-12-31"):
        Selection(measure_id=measure, year=2023)


@pytest.mark.parametrize(
    "changes",
    [
        {"year": 2022},
        {"vintage_year": 2023},
        {"vintage_year": True},
        {"vintage_year": "2022"},
        {"vintage_year": 2022, "year": 2022},
        {"vintage_year": 2022, "start_date": "2022-01-01", "end_date": "2022-01-01"},
        {"vintage_year": None},
        {},
    ],
)
def test_invalid_context_selections_do_not_coerce(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Selection.model_validate({"measure_id": "population_2022", **changes})


@pytest.mark.parametrize("fault", ["vintage", "unknown", "dates"])
def test_context_response_mismatch_fails_without_evidence(fault: str) -> None:
    page = context_page("population_2022", 2022)
    row = page["data"][0]
    if fault == "vintage":
        row["county_context"]["vintage_year"] = 2023
    elif fault == "unknown":
        row["county_context"]["private_field"] = "do not expose"
    else:
        row["period_start"] = None
    server = create_server(
        client=AtlasClient(
            "https://api.onehealthatlas.org",
            httpx.MockTransport(lambda _: httpx.Response(200, json=copy.deepcopy(page))),
        )
    )
    result = asyncio.run(
        server.call_tool(
            "atlas_get_county_profile",
            {
                "county_fips": "42029",
                "selections": [{"measure_id": "population_2022", "vintage_year": 2022}],
            },
        )
    )
    assert isinstance(result, CallToolResult)
    assert result.is_error
    assert result.structured_content["code"] == "UPSTREAM_CONTRACT_INVALID"
    assert "observations" not in result.structured_content
    assert "do not expose" not in str(result)


def test_mixed_cumulative_and_population_profile_preserves_all_three_selections() -> None:
    selections = [
        {"measure_id": m, "start_date": "2025-12-31", "end_date": "2025-12-31"}
        for m in ("scapularis_status", "burgdorferi_status")
    ] + [{"measure_id": "population_2022", "vintage_year": 2022}]

    def handler(request: httpx.Request) -> httpx.Response:
        measure = request.url.params["measure_id"]
        page = context_page(measure, 2022)
        if measure != "population_2022":
            assert "vintage_year" not in request.url.params
            assert (
                request.url.params["start_date"] == request.url.params["end_date"] == "2025-12-31"
            )
            row = page["data"][0]
            del row["county_context"]
            row.update(
                temporal_grain="CUMULATIVE",
                period_start="2025-12-31",
                period_end="2025-12-31",
                value="No records",
                value_state="NO_RECORDS",
            )
        page["meta"]["limitations"] = ["Preserve original selection limitations."]
        return httpx.Response(200, json=page)

    server = create_server(
        client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
    )
    result = asyncio.run(
        server.call_tool(
            "atlas_get_county_profile", {"county_fips": "42029", "selections": selections}
        )
    )
    assert isinstance(result, CallToolResult)
    assert not result.is_error, result
    rows = result.structured_content["selections"]
    assert [r["request"] for r in rows] == selections
    assert all(
        r["availability"]["limitations"] == ["Preserve original selection limitations."]
        for r in rows
    )
    assert rows[0]["observations"][0]["value_state"] == "NO_RECORDS"
    assert rows[2]["observations"][0]["period_start"] == "2018-01-01"


def test_context_comparison_retains_null_category_dates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = context_page("rucc_2023", 2023)
        page["data"][0]["geography"]["geography_id"] = request.url.params["geography_id"]
        return httpx.Response(200, json=page)

    server = create_server(
        client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
    )
    result = asyncio.run(
        server.call_tool(
            "atlas_compare_counties",
            {
                "county_fips": ["42029", "42091"],
                "selections": [{"measure_id": "rucc_2023", "vintage_year": 2023}],
            },
        )
    )
    assert isinstance(result, CallToolResult)
    assert not result.is_error, result
    assert result.structured_content["complete"] is True
    for county in result.structured_content["matrix"][0]["counties"]:
        assert county["observations"][0]["period_start"] is None
        assert county["observations"][0]["county_context"]["vintage_year"] == 2023
