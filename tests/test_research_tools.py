"""Research tools preserve publisher semantics and fail closed under bounded retrieval."""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from atlas_lyme_mcp.application.client import AtlasClient
from atlas_lyme_mcp.server import create_server
from atlas_lyme_mcp.tools.research import output_schema

FIXTURES = Path(__file__).parent / "fixtures"
SELECTION = {"measure_id": "case_count_floor_2023", "year": 2023}
COMPARE = {"county_fips": ["01001", "01003"], "selections": [SELECTION]}


def fixture(name: str) -> dict[str, Any]:
    return dict(json.loads((FIXTURES / name).read_text(encoding="utf-8-sig")))


def call(name: str, args: dict[str, Any], handler: Any) -> Any:
    return asyncio.run(
        create_server(
            client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
        ).call_tool(name, args)
    )


def observation(request: httpx.Request) -> dict[str, Any]:
    page = fixture("public-observations.json")
    page["data"][0]["geography"]["geography_id"] = request.url.params["geography_id"]
    return page


def test_comparison_preserves_missing_and_zero_without_ranking() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = observation(request)
        if request.url.params["geography_id"] == "01003":
            page["data"][0].update(value=0, value_state="ZERO")
        return httpx.Response(200, json=page)

    result = call("atlas_compare_counties", COMPARE, handler)
    assert not result.is_error
    rows = result.structured_content["matrix"][0]["counties"]
    assert rows[0]["observations"][0]["value_state"] == "MISSING"
    assert rows[1]["observations"][0]["value_state"] == "ZERO"
    assert "rank" not in result.structured_content


@pytest.mark.parametrize("mismatch", [False, True])
def test_identical_multi_period_series_not_falsely_incompatible(mismatch: bool) -> None:
    args = copy.deepcopy(COMPARE)
    args["selections"] = [
        {
            "measure_id": "case_count_floor_2023",
            "start_date": "2023-01-01",
            "end_date": "2023-01-02",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        page = observation(request)
        base = page["data"][0]
        base.update(period_start="2023-01-01", period_end="2023-01-01", temporal_grain="DAY")
        second = copy.deepcopy(base)
        second.update(observation_id="second", period_start="2023-01-02", period_end="2023-01-02")
        second["evidence"]["resource_id"] = "second"
        if mismatch and request.url.params["geography_id"] == "01003":
            second["unit"] = "different_unit"
        page["data"].append(second)
        return httpx.Response(200, json=page)

    result = call("atlas_compare_counties", args, handler)
    assert not result.is_error
    assert result.structured_content["matrix"][0]["comparability"] == (
        "incompatible" if mismatch else "not_established"
    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("page", "EVIDENCE_INCOMPLETE"),
        ("release", "RELEASE_CHANGED"),
        ("empty", "EVIDENCE_INCOMPLETE"),
        ("malformed", "UPSTREAM_CONTRACT_INVALID"),
        ("oversized", "RESULT_TOO_LARGE"),
        ("timeout", "UPSTREAM_UNAVAILABLE"),
        ("429", "RATE_LIMITED"),
        ("503", "UPSTREAM_UNAVAILABLE"),
    ],
)
def test_comparison_failure_never_returns_partial_evidence(fault: str, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = observation(request)
        if fault == "page":
            page["meta"]["next_page_token"] = "more"
        if fault == "release" and request.url.params["geography_id"] == "01003":
            page["data"][0]["release_id"] = "changed"
            page["data"][0]["evidence"]["release_id"] = "changed"
        if fault == "empty":
            page["data"] = []
        if fault == "malformed":
            page["data"][0]["value_state"] = "invented"
        if fault == "oversized":
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b" " * 300000
            )
        if fault == "timeout":
            raise httpx.ReadTimeout("private text")
        if fault in {"429", "503"}:
            return httpx.Response(int(fault), text="private text")
        return httpx.Response(200, json=page)

    result = call("atlas_compare_counties", COMPARE, handler)
    assert result.is_error and result.structured_content["code"] == code
    assert "private text" not in str(result)
    assert "matrix" not in result.structured_content


@pytest.mark.parametrize(
    "args",
    [
        {"county_fips": ["01001"]},
        {"county_fips": ["01001", "01001"]},
        {"county_fips": ["1", "01001"]},
        {"selections": [{"measure_id": "x", "year": True}]},
        {"selections": [{"measure_id": "x", "start_date": "2023-02-30", "end_date": "2023-03-01"}]},
    ],
)
def test_invalid_compare_never_calls_upstream(args: dict[str, Any]) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream called")

    with pytest.raises(ToolError):
        call("atlas_compare_counties", COMPARE | args, forbidden)


@pytest.mark.parametrize(
    "state", ["SUFFICIENT", "INSUFFICIENT", "NOT_ESTIMABLE", "NO_PUBLISHED_MODEL"]
)
def test_priority_preserves_published_sufficiency_and_absence(state: str) -> None:
    item = fixture("research-priority.json")
    if state == "NO_PUBLISHED_MODEL":
        item.update(availability="UNAVAILABLE", reason=state, data=None)
    else:
        item["data"]["evidence_sufficiency"] = state
        if state == "NOT_ESTIMABLE":
            for field in ["priority_tier", "raw_model_score", "priority_percentile"]:
                item["data"][field] = None
    result = call(
        "atlas_get_surveillance_priority",
        {"county_fips": ["09110"]},
        lambda _: httpx.Response(200, json=item),
    )
    assert not result.is_error
    assert result.structured_content["counties"][0]["availability"] == item
    assert "not predicted disease risk" in " ".join(result.structured_content["limitations"])


def test_priority_rejects_wrong_county_or_invalid_abstention() -> None:
    item = fixture("research-priority.json")
    item["data"]["evidence_sufficiency"] = "NOT_ESTIMABLE"
    result = call(
        "atlas_get_surveillance_priority",
        {"county_fips": ["09110"]},
        lambda _: httpx.Response(200, json=item),
    )
    assert result.is_error


def test_disabled_state_review_preserves_unsupported_and_coverage() -> None:
    item = fixture("research-review.json")
    result = call("atlas_review_state", {"state": "CT"}, lambda _: httpx.Response(200, json=item))
    assert not result.is_error and result.structured_content["review"] == item
    item["result_state"] = "none_stand_out"
    assert call(
        "atlas_review_state", {"state": "CT"}, lambda _: httpx.Response(200, json=item)
    ).is_error


def test_scores_use_bounded_county_route_and_exact_publisher_values() -> None:
    county = fixture("research-county.json")
    metadata = fixture("research-metadata.json")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path in {"/v1/atlas/metadata", "/v1/counties/09110"}
        return httpx.Response(
            200, json=metadata if request.url.path.endswith("metadata") else county
        )

    result = call("atlas_get_atlas_scores", {"county_fips": ["09110"]}, handler)
    assert not result.is_error and result.structured_content["counties"] == [county]
    assert calls == ["/v1/atlas/metadata", "/v1/counties/09110"]
    county["release"]["release_id"] = "changed"
    assert (
        call("atlas_get_atlas_scores", {"county_fips": ["09110"]}, handler).structured_content[
            "code"
        ]
        == "RELEASE_CHANGED"
    )


@pytest.mark.parametrize("published_version", [False, True])
def test_scores_preserve_optional_published_scoring_methodology(published_version: bool) -> None:
    metadata = fixture("research-metadata.json")
    if published_version:
        metadata["scoring_methodology_version"] = "surveillance-gap-score-v1.1"
    counties = []
    for fips in ["42029", "42091"]:
        county = fixture("research-county.json")
        county.update(fips=fips, release=copy.deepcopy(metadata))
        if published_version:
            county["scoring_methodology_version"] = "surveillance-gap-score-v1.1"
        counties.append(county)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/atlas/metadata":
            return httpx.Response(200, json=metadata)
        county = next(c for c in counties if request.url.path.endswith(c["fips"]))
        assert request.url.params["dataset_version"] == metadata["release_id"]
        return httpx.Response(200, json=county)

    result = call("atlas_get_atlas_scores", {"county_fips": ["42029", "42091"]}, handler)
    assert not result.is_error
    assert result.structured_content["metadata"] == metadata
    assert result.structured_content["counties"] == counties
    assert result.structured_content["metadata"]["limitations"] == metadata["limitations"]


@pytest.mark.parametrize("location", ["metadata", "county", "release"])
@pytest.mark.parametrize(
    "field,value",
    [("unreviewed_field", "private"), ("scoring_methodology_version", "unreviewed-version")],
)
def test_scores_reject_unreviewed_contract_changes(location: str, field: str, value: str) -> None:
    metadata = fixture("research-metadata.json")
    county = fixture("research-county.json")
    target = {"metadata": metadata, "county": county, "release": county["release"]}[location]
    target[field] = value
    result = call(
        "atlas_get_atlas_scores",
        {"county_fips": [county["fips"]]},
        lambda r: httpx.Response(200, json=metadata if r.url.path.endswith("metadata") else county),
    )
    assert result.is_error
    assert result.structured_content["code"] == "UPSTREAM_CONTRACT_INVALID"
    assert result.structured_content["retryable"] is False
    assert "private" not in str(result)


def test_brief_retains_observation_citations_and_resolves_exact_references() -> None:
    page = fixture("public-observations.json")
    source = fixture("public-source.json")
    # A canonical methodology from the pinned schema, explicitly synthetic fixture.
    from atlas_lyme_mcp.application.public_schema import DOCUMENT

    schema = DOCUMENT["components"]["schemas"]["Methodology"]
    method: dict[str, Any] = {k: None for k in schema["required"]}
    for k, v in schema["properties"].items():
        if v.get("type") == "string":
            method[k] = "fixture"
        if v.get("type") == "array":
            method[k] = []
    method.update(
        methodology_id=page["data"][0]["methodology_id"],
        release_version=page["data"][0]["release_id"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("observations"):
            return httpx.Response(200, json=page)
        if "/sources/" in request.url.path:
            return httpx.Response(200, json=source)
        return httpx.Response(200, json={"data": method})

    result = call(
        "atlas_build_evidence_brief", {"county_fips": "01001", "selections": [SELECTION]}, handler
    )
    assert not result.is_error, result
    assert result.structured_content["reference_ids"] == [page["data"][0]["evidence"]]
    assert len(result.structured_content["resources"]) == 2


def test_brief_unknown_methodology_fails_explicitly_without_lookup() -> None:
    page = fixture("public-observations.json")
    page["data"][0]["methodology_id"] = None
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=page)

    result = call(
        "atlas_build_evidence_brief", {"county_fips": "01001", "selections": [SELECTION]}, handler
    )
    assert result.is_error and result.structured_content["code"] == "EVIDENCE_INCOMPLETE"
    assert calls == ["/v1/observations"]


def test_research_output_schemas_are_closed_and_self_contained() -> None:
    from jsonschema import Draft202012Validator

    for name in [
        "atlas_compare_counties",
        "atlas_get_surveillance_priority",
        "atlas_get_atlas_scores",
        "atlas_review_state",
        "atlas_build_evidence_brief",
    ]:
        schema = output_schema(name)
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize("metadata_release", ["absent", None, "other-release"])
def test_mixed_empty_selection_cannot_borrow_another_release(metadata_release: str | None) -> None:
    args = {
        "county_fips": "01001",
        "selections": [SELECTION, {"measure_id": "empty_measure", "year": 2023}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = observation(request)
        if request.url.params["measure_id"] == "empty_measure":
            page["data"] = []
            if metadata_release != "absent":
                page["meta"]["release_id"] = metadata_release
        return httpx.Response(200, json=page)

    result = call("atlas_build_evidence_brief", args, handler)
    assert result.is_error
    assert result.structured_content["code"] == (
        "RELEASE_CHANGED" if metadata_release == "other-release" else "EVIDENCE_INCOMPLETE"
    )


def test_complete_empty_release_preserves_availability_without_inventing_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = observation(request)
        release = page["data"][0]["release_id"]
        page["data"] = []
        page["meta"].update(
            release_id=release,
            availability="UNAVAILABLE",
            reason="NO_PUBLISHED_RESULTS",
            limitations=["No published selection rows."],
        )
        return httpx.Response(200, json=page)

    result = call("atlas_compare_counties", COMPARE, handler)
    assert not result.is_error
    row = result.structured_content["matrix"][0]["counties"][0]
    assert row["observations"] == [] and row["availability"]["reason"] == "NO_PUBLISHED_RESULTS"


def test_maximum_comparison_fanout_is_fifteen_calls() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        page = observation(request)
        page["data"][0]["measure_id"] = request.url.params["measure_id"]
        return httpx.Response(200, json=page)

    result = call(
        "atlas_compare_counties",
        {
            "county_fips": ["01001", "01003", "01005", "01007", "01009"],
            "selections": [{"measure_id": f"measure_{i}", "year": 2023} for i in range(3)],
        },
        handler,
    )
    assert not result.is_error and count == 15


def test_composed_result_size_is_enforced_even_when_each_page_fits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = observation(request)
        page["data"][0]["limitations"] = ["public caveat " * 11000]
        page["data"][0]["measure_id"] = request.url.params["measure_id"]
        response = httpx.Response(200, json=page)
        assert len(response.content) < 256 * 1024
        return response

    # Four individually bounded pages exceed the approved comparison-only 512 KiB cap.
    args = COMPARE | {"selections": [SELECTION, {"measure_id": "other", "year": 2023}]}
    result = call("atlas_compare_counties", args, handler)
    assert result.is_error and result.structured_content["code"] == "RESULT_TOO_LARGE"


def test_shared_client_caps_real_http_concurrency_and_releases_on_cancellation() -> None:
    async def run() -> None:
        entered = 0
        ready = asyncio.Event()
        release = asyncio.Event()

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal entered
            entered += 1
            if entered == 3:
                ready.set()
            await release.wait()
            return httpx.Response(200, json=fixture("research-metadata.json"))

        client = AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
        calls = [
            asyncio.create_task(client.get("atlas_metadata", None, "research:AtlasMetadata"))
            for _ in range(3)
        ]
        await ready.wait()
        from atlas_lyme_mcp.application.client import RetrievalError

        with pytest.raises(RetrievalError, match="RATE_LIMITED"):
            await client.get("atlas_metadata", None, "research:AtlasMetadata")
        assert entered == 3 and client.active == 3
        for task in calls:
            task.cancel()
        await asyncio.gather(*calls, return_exceptions=True)
        assert client.active == 0

    asyncio.run(run())
