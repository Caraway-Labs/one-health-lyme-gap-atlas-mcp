"""Canonical public fixtures and hostile service responses exercise the real adapters."""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult

from atlas_lyme_mcp.application.client import REQUEST_ID, TRACEPARENT, AtlasClient
from atlas_lyme_mcp.server import create_server
from atlas_lyme_mcp.tools.contracts import ProfileArguments
from atlas_lyme_mcp.tools.evidence import EvidenceTools

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE: dict[str, Any] = {
    "county_fips": "01001",
    "selections": [{"measure_id": "case_count_floor_2023", "year": 2023}],
}
RELEASE = "governed-2026-10-06-nlcd-demo-cohort"


def fixture(name: str) -> dict[str, Any]:
    return dict(json.loads((FIXTURES / f"public-{name}.json").read_text(encoding="utf-8-sig")))


def call(name: str, arguments: dict[str, Any], handler: Any) -> CallToolResult:
    server = create_server(
        client=AtlasClient("https://api.onehealthatlas.org", httpx.MockTransport(handler))
    )
    result = asyncio.run(server.call_tool(name, arguments))
    assert isinstance(result, CallToolResult)
    return result


def test_all_tools_have_strict_input_and_canonical_output_schemas() -> None:
    tools = asyncio.run(create_server().list_tools())
    assert {t.name for t in tools} == {
        "server_status",
        "atlas_smoke_test",
        "atlas_discover_indicators",
        "atlas_get_county_profile",
        "atlas_get_evidence_provenance",
        "atlas_resolve_geographies",
    }
    for tool in tools:
        if tool.name.startswith("atlas_") and tool.name != "atlas_smoke_test":
            assert tool.input_schema["additionalProperties"] is False
            Draft202012Validator.check_schema(tool.input_schema)
            assert tool.output_schema is not None
            Draft202012Validator.check_schema(tool.output_schema)
    profile = next(t for t in tools if t.name == "atlas_get_county_profile")
    Draft202012Validator(profile.input_schema).validate(PROFILE)
    with pytest.raises(SchemaError):
        Draft202012Validator(profile.input_schema).validate(PROFILE | {"county_fips": "1001"})


@pytest.mark.parametrize(
    "change",
    [
        {"county_fips": "1001"},
        {"county_fips": "０１００１"},
        {"county_fips": 1001},
        {"county_fips": " 01001"},
        {"url": "http://169.254.169.254"},
        {"selections": []},
        {"selections": json.dumps(PROFILE["selections"])},
        {"selections": PROFILE["selections"] * 4},
        {"selections": [{"measure_id": "case_count_floor_2023", "year": "2023"}]},
        {"selections": [{"measure_id": "case_count_floor_2023", "year": True}]},
        {"selections": [{"measure_id": "x", "year": 2023, "start_date": "2023-01-01"}]},
        {"selections": [{"measure_id": "x", "start_date": "2023-02-30", "end_date": "2023-03-01"}]},
        {"selections": [{"measure_id": "x", "start_date": "2023-01-01", "end_date": "2023-02-01"}]},
        {"selections": [{"measure_id": "x", "start_date": "2023-02-01", "end_date": "2023-01-01"}]},
        {"selections": PROFILE["selections"] * 2},
    ],
)
def test_invalid_arguments_never_reach_backend(change: dict[str, Any]) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid input reached backend")

    with pytest.raises(ToolError):
        call("atlas_get_county_profile", PROFILE | change, forbidden)


@pytest.mark.parametrize(
    "state,value",
    [
        ("MISSING", None),
        ("SUPPRESSED", None),
        ("UNAVAILABLE", None),
        ("ZERO", 0),
        ("OBSERVED", 5),
        ("NO_RECORDS", "No records"),
        ("NO_COUNTY_LINKED_RECORD", "no_county_linked_record"),
    ],
)
def test_observation_fidelity_and_leading_zero(state: str, value: Any) -> None:
    page = fixture("observations")
    page["data"][0].update(value_state=state, value=value)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["geography_id"] == "01001"
        assert request.url.params["year"] == "2023"
        assert request.url.path == "/v1/observations"
        return httpx.Response(200, json=page)

    result = call("atlas_get_county_profile", PROFILE, handler)
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["selections"][0]["observations"] == page["data"]
    assert json.loads(result.content[0].text) == result.structured_content  # type: ignore[union-attr]


def test_discovery_composes_bounded_related_pages() -> None:
    indicators = fixture("indicators")
    indicators["data"] = [indicators["data"][1]]
    indicators["meta"]["next_page_token"] = "indicator-cursor"
    measures = fixture("measures")
    measures["data"] = [measures["data"][1]]
    measures["meta"]["next_page_token"] = "measure-cursor"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/indicators":
            assert request.url.params["page_token"] == "indicator-cursor"
            return httpx.Response(200, json=indicators)
        assert request.url.path == "/v1/measures"
        assert request.url.params["indicator_id"] == "human_disease_burden"
        return httpx.Response(200, json=measures)

    result = call(
        "atlas_discover_indicators", {"page_token": "indicator-cursor", "page_size": 1}, handler
    )
    assert result.structured_content is not None
    assert result.structured_content["indicators"] == indicators["data"]
    assert result.structured_content["measures"] == measures["data"]
    assert result.structured_content["meta"]["measure_page_tokens"] == {
        "human_disease_burden": "measure-cursor"
    }
    assert len(requests) == 2


def test_provenance_preserves_source_timestamps_and_expected_release() -> None:
    source = fixture("source")
    result = call(
        "atlas_get_evidence_provenance",
        {
            "reference_type": "source",
            "reference_id": "human",
            "expected_release_id": RELEASE,
        },
        lambda _: httpx.Response(200, json=source),
    )
    assert result.structured_content is not None
    assert result.structured_content["resource"] == source["data"]
    assert source["data"]["source_retrieved_at"] is None
    mismatch = call(
        "atlas_get_evidence_provenance",
        {
            "reference_type": "source",
            "reference_id": "human",
            "expected_release_id": "old-release",
        },
        lambda _: httpx.Response(200, json=source),
    )
    assert mismatch.is_error and mismatch.structured_content is not None
    assert mismatch.structured_content["code"] == "RELEASE_CHANGED"


def test_methodology_reference_resolution_uses_fixed_detail_path() -> None:
    methodology = {
        "methodology_id": "human_confirmed_probable_case_floor_v1",
        "measure_id": "case_count_floor_2023",
        "version": "1.0.0",
        "description": "Published floor",
        "limitations": ["Not complete incidence"],
        "semantic_version": "1.0.0",
        "release_version": RELEASE,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/methodologies/human_confirmed_probable_case_floor_v1"
        assert not request.url.query
        return httpx.Response(200, json={"data": methodology})

    result = call(
        "atlas_get_evidence_provenance",
        {
            "reference_type": "methodology",
            "reference_id": methodology["methodology_id"],
            "expected_release_id": RELEASE,
        },
        handler,
    )
    assert result.structured_content is not None
    assert result.structured_content["resource"] == methodology


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("atlas_discover_indicators", {"page_size": 6}),
        ("atlas_discover_indicators", {"page_size": True}),
        ("atlas_discover_indicators", {"page_token": "x" * 2049}),
        ("atlas_discover_indicators", {"measure_page_token": "x"}),
        ("atlas_discover_indicators", {"indicator_id": "../private"}),
        (
            "atlas_get_evidence_provenance",
            {"reference_type": "observation", "reference_id": "x", "expected_release_id": RELEASE},
        ),
        (
            "atlas_get_evidence_provenance",
            {
                "reference_type": "source",
                "reference_id": "https://example.org",
                "expected_release_id": RELEASE,
            },
        ),
    ],
)
def test_discovery_and_provenance_invalid_inputs_never_call_backend(
    name: str, arguments: dict[str, Any]
) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid arguments reached upstream")

    with pytest.raises(ToolError):
        call(name, arguments, forbidden)


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(504, text="<html>private backend detail</html>"), "UPSTREAM_UNAVAILABLE"),
        (httpx.Response(503, json={"detail": "private"}), "UPSTREAM_UNAVAILABLE"),
        (httpx.Response(404, json={"detail": "private"}), "RESOURCE_NOT_FOUND"),
        (httpx.Response(400, json={"detail": "unsupported period"}), "INVALID_REQUEST"),
        (httpx.Response(429, headers={"Retry-After": "5"}), "RATE_LIMITED"),
        (
            httpx.Response(302, headers={"Location": "http://169.254.169.254"}),
            "UPSTREAM_UNAVAILABLE",
        ),
        (httpx.Response(200, text="<html>private</html>"), "UPSTREAM_CONTRACT_INVALID"),
        (
            httpx.Response(200, content="broken", headers={"Content-Type": "application/json"}),
            "UPSTREAM_CONTRACT_INVALID",
        ),
        (httpx.Response(200, json={"data": []}), "UPSTREAM_CONTRACT_INVALID"),
        (
            httpx.Response(
                200, content=b"x" * 262145, headers={"Content-Type": "application/json"}
            ),
            "RESULT_TOO_LARGE",
        ),
    ],
)
def test_safe_service_failures(response: httpx.Response, code: str) -> None:
    result = call("atlas_get_county_profile", PROFILE, lambda _: response)
    assert result.is_error and result.structured_content is not None
    assert result.structured_content["code"] == code
    assert "private" not in str(result) and "<html>" not in str(result)


def test_timeout_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private backend", request=request)

    result = call("atlas_get_county_profile", PROFILE, handler)
    assert result.is_error and "private" not in str(result)


def test_unreviewed_response_fields_are_not_forwarded() -> None:
    page = fixture("observations")
    page["data"][0]["internal_authority_proof"] = "private-value"
    result = call("atlas_get_county_profile", PROFILE, lambda _: httpx.Response(200, json=page))
    assert result.is_error and result.structured_content is not None
    assert result.structured_content["code"] == "UPSTREAM_CONTRACT_INVALID"
    assert "private-value" not in str(result)


@pytest.mark.parametrize(
    "mutation", ["county", "measure", "period", "release", "state", "too_many", "duplicate"]
)
def test_backend_semantic_mismatches_fail_closed(mutation: str) -> None:
    page = fixture("observations")
    item = page["data"][0]
    if mutation == "county":
        item["geography"]["geography_id"] = "08001"
    elif mutation == "measure":
        item["measure_id"] = "other"
    elif mutation == "period":
        item["period_start"] = "2024-01-01"
    elif mutation == "release":
        item["evidence"]["release_id"] = "other"
    elif mutation == "state":
        item["value"] = 0
    elif mutation == "too_many":
        page["data"] *= 32
    else:
        page["data"].append(copy.deepcopy(item))
    result = call("atlas_get_county_profile", PROFILE, lambda _: httpx.Response(200, json=page))
    assert result.is_error


def test_independent_selections_reject_mixed_releases_and_keep_empty_distinct() -> None:
    page = fixture("observations")
    empty = copy.deepcopy(page)
    empty["data"] = []
    result = call("atlas_get_county_profile", PROFILE, lambda _: httpx.Response(200, json=empty))
    assert result.structured_content is not None
    assert result.structured_content["selections"][0]["retrieval_state"] == "empty"
    assert result.structured_content["meta"]["release_id"] is None
    count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        data = copy.deepcopy(page)
        if count == 2:
            data["data"][0].update(release_id="other", measure_id="incidence_floor_2023")
            data["data"][0]["evidence"]["release_id"] = "other"
        return httpx.Response(200, json=data)

    request = PROFILE | {
        "selections": PROFILE["selections"] + [{"measure_id": "incidence_floor_2023", "year": 2023}]
    }
    result = call("atlas_get_county_profile", request, handler)
    assert result.is_error and result.structured_content is not None
    assert result.structured_content["code"] == "RELEASE_CHANGED"


def test_correlation_forwarding_and_concurrency_rejection_before_io() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Request-ID"] == "atlas-test-1"
        assert request.headers["traceparent"] == "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
        return httpx.Response(200, json=fixture("observations"))

    t1 = REQUEST_ID.set("atlas-test-1")
    t2 = TRACEPARENT.set("00-" + "1" * 32 + "-" + "2" * 16 + "-01")
    try:
        assert not call("atlas_get_county_profile", PROFILE, handler).is_error
    finally:
        REQUEST_ID.reset(t1)
        TRACEPARENT.reset(t2)
    runtime = EvidenceTools(AtlasClient("https://api.onehealthatlas.org"))
    runtime.active = 3

    async def must_not_run() -> dict[str, Any]:
        raise AssertionError("over-budget work started")

    result = asyncio.run(runtime.invoke("atlas_get_county_profile", must_not_run()))
    assert result.is_error


def test_shared_validation_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def shared(value: str) -> str:
        seen.append(value)
        return value

    monkeypatch.setattr("atlas_lyme_mcp.tools.contracts.normalize_county_fips", shared)
    assert ProfileArguments.model_validate(PROFILE).county_fips == "01001"
    assert seen == ["01001"]


def test_output_aggregate_budget_returns_no_partial_evidence() -> None:
    page = fixture("observations")
    page["data"][0]["limitations"] = ["x" * 100000]

    def handler(request: httpx.Request) -> httpx.Response:
        body = copy.deepcopy(page)
        body["data"][0]["measure_id"] = request.url.params["measure_id"]
        return httpx.Response(200, json=body)

    arguments = PROFILE | {
        "selections": [{"measure_id": measure, "year": 2023} for measure in ("a", "b", "c")]
    }
    result = call("atlas_get_county_profile", arguments, handler)
    assert result.is_error and result.structured_content is not None
    assert result.structured_content["code"] == "RESULT_TOO_LARGE"
    assert "observations" not in result.structured_content


def test_whole_tool_deadline_and_downstream_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas_lyme_mcp.application.client import RetrievalError

    timeout = asyncio.timeout
    monkeypatch.setattr("atlas_lyme_mcp.tools.evidence.asyncio.timeout", lambda _: timeout(0.01))

    async def delayed() -> dict[str, Any]:
        await asyncio.sleep(1)
        return {}

    runtime = EvidenceTools(AtlasClient("https://api.onehealthatlas.org"))
    result = asyncio.run(runtime.invoke("atlas_get_county_profile", delayed()))
    assert result.is_error and runtime.active == 0
    import time

    runtime.client.calls.extend([time.monotonic()] * 50)
    with pytest.raises(RetrievalError, match="RATE_LIMITED"):
        asyncio.run(runtime.client.get("observations", {}, "CollectionEnvelope_Observation_"))
