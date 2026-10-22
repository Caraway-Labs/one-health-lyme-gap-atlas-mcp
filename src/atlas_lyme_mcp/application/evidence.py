"""Bounded composition of canonical public evidence; no scientific interpretation."""

from datetime import date
from typing import Any

from atlas_lyme_mcp.application.client import AtlasClient, RetrievalError
from atlas_lyme_mcp.tools.contracts import (
    DiscoveryArguments,
    ProfileArguments,
    ProvenanceArguments,
)


def same_release(
    items: list[dict[str, Any]], field: str, expected: str | None = None
) -> str | None:
    releases = {item[field] for item in items}
    if None in releases or len(releases) > 1 or (expected and releases and releases != {expected}):
        raise RetrievalError("RELEASE_CHANGED")
    return next(iter(releases), expected)


async def discover(client: AtlasClient, request: DiscoveryArguments) -> dict[str, Any]:
    params: dict[str, str | int] = {"page_size": request.page_size}
    if request.indicator_id:
        params["indicator_id"] = request.indicator_id
    if request.page_token:
        params["page_token"] = request.page_token
    page = await client.get("indicators", params, "CollectionEnvelope_Indicator_")
    indicators = page["data"]
    if len(indicators) > request.page_size or any(
        request.indicator_id and i["indicator_id"] != request.indicator_id for i in indicators
    ):
        raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
    release = same_release(indicators, "release_version")
    measures: list[dict[str, Any]] = []
    continuations: dict[str, str] = {}
    for indicator in indicators:
        query: dict[str, str | int] = {"indicator_id": indicator["indicator_id"], "page_size": 20}
        if request.measure_page_token:
            query["page_token"] = request.measure_page_token
        result = await client.get("measures", query, "CollectionEnvelope_Measure_")
        data = result["data"]
        if len(data) > 20 or any(
            m["indicator_id"] != indicator["indicator_id"]
            or m["measure_id"] not in indicator["measure_ids"]
            for m in data
        ):
            raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        same_release(data, "release_version", release)
        measures.extend(data)
        if token := result["meta"]["next_page_token"]:
            continuations[indicator["indicator_id"]] = token
    return {
        "indicators": indicators,
        "measures": measures,
        "meta": {**page["meta"], "release_id": release, "measure_page_tokens": continuations},
    }


async def profile(
    client: AtlasClient, request: ProfileArguments, *, include_selection_meta: bool = False
) -> dict[str, Any]:
    selections: list[dict[str, Any]] = []
    release: str | None = None
    response_at: str | None = None
    for selection in request.selections:
        query = selection.model_dump(exclude_none=True)
        query.update(geography_type="county", geography_id=request.county_fips, page_size=31)
        contract = (
            "context:CollectionEnvelope_CountyContextObservation_"
            if selection.vintage_year is not None
            else "CollectionEnvelope_Observation_"
        )
        page = await client.get("observations", query, contract)
        observations = page["data"]
        if len(observations) > 31:
            raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        release = same_release(observations, "release_id", release)
        start = (
            date(selection.year, 1, 1)
            if selection.year
            else date.fromisoformat(selection.start_date)
            if selection.start_date
            else None
        )
        end = (
            date(selection.year, 12, 31)
            if selection.year
            else date.fromisoformat(selection.end_date)
            if selection.end_date
            else None
        )
        ids: set[str] = set()
        for item in observations:
            if (
                item["measure_id"] != selection.measure_id
                or item["geography"]
                != {"geography_type": "county", "geography_id": request.county_fips}
                or (
                    selection.vintage_year is None
                    and not (
                        start is not None
                        and end is not None
                        and start
                        <= date.fromisoformat(item["period_start"])
                        <= date.fromisoformat(item["period_end"])
                        <= end
                    )
                )
                or item["observation_id"] in ids
                or item["evidence"]["resource_id"] != item["observation_id"]
                or item["evidence"]["release_id"] != item["release_id"]
            ):
                raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
            if selection.vintage_year is not None:
                if item["county_context"]["vintage_year"] != selection.vintage_year:
                    raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
                if item["temporal_grain"] == "VINTAGE_YEAR":
                    if item["period_start"] is not None or item["period_end"] is not None:
                        raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
                elif (
                    item["period_start"] is None
                    or item["period_end"] is None
                    or date.fromisoformat(item["period_start"])
                    > date.fromisoformat(item["period_end"])
                ):
                    raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
            ids.add(item["observation_id"])
            # These are transport fidelity invariants from canonical Observation validation.
            state, value = item["value_state"], item["value"]
            if (
                (state in {"MISSING", "SUPPRESSED", "UNAVAILABLE"} and value is not None)
                or (state == "ZERO" and (isinstance(value, bool) or value != 0))
                or (state == "OBSERVED" and value in (None, 0))
                or (state == "NO_RECORDS" and value != "No records")
                or (state == "NO_COUNTY_LINKED_RECORD" and value != "no_county_linked_record")
            ):
                raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        if include_selection_meta and page["meta"].get("release_id"):
            release = same_release([page["meta"]], "release_id", release)
        response_at = page["meta"]["response_at"]
        selections.append(
            {
                "request": selection.model_dump(exclude_none=True),
                "observations": observations,
                "retrieval_state": "returned" if observations else "empty",
                "next_page_token": page["meta"]["next_page_token"],
                "availability": page["meta"],
            }
        )
    return {
        "county_fips": request.county_fips,
        "selections": selections,
        "meta": {"release_id": release, "response_at": response_at},
    }


async def provenance(client: AtlasClient, request: ProvenanceArguments) -> dict[str, Any]:
    resource = "sources" if request.reference_type == "source" else "methodologies"
    contract = (
        "ResourceEnvelope_Source_"
        if request.reference_type == "source"
        else "ResourceEnvelope_Methodology_"
    )
    page = await client.get(resource, None, contract, request.reference_id)
    item = page["data"]
    key = "source_id" if request.reference_type == "source" else "methodology_id"
    if item[key] != request.reference_id:
        raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
    same_release([item], "release_version", request.expected_release_id)
    return {
        "reference_type": request.reference_type,
        "reference_id": request.reference_id,
        "resource": item,
        "meta": {"release_id": item["release_version"]},
    }
