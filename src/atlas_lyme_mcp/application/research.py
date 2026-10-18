"""Bounded research orchestration; canonical evidence remains unchanged."""

import asyncio
from collections.abc import Awaitable
from typing import Any, Literal, cast

from atlas_lyme_mcp.application.client import REQUEST_ID, AtlasClient, RetrievalError
from atlas_lyme_mcp.application.evidence import profile, provenance, same_release
from atlas_lyme_mcp.tools.contracts import ProfileArguments, ProvenanceArguments
from atlas_lyme_mcp.tools.research_contracts import (
    BriefArguments,
    CompareArguments,
    CountiesArguments,
    ReviewArguments,
    ScoresArguments,
)

LIMITATIONS = [
    (
        "Descriptive published evidence only; no epidemiological "
        "conclusions, significance, disease risk or clinical advice."
    ),
    "Empty evidence is not zero, biological absence or verified evidence adequacy.",
]


async def bounded(operations: list[Awaitable[dict[str, Any]]]) -> list[dict[str, Any]]:
    """At most three concurrent calls; cancel and close all remaining work on failure."""
    results: list[dict[str, Any]] = []
    consumed = 0
    try:
        for start in range(0, len(operations), 3):
            batch = operations[start : start + 3]
            consumed += len(batch)
            values = await asyncio.gather(*batch, return_exceptions=True)
            for value in values:
                if isinstance(value, BaseException):
                    raise value
                results.append(value)
        return results
    finally:
        for operation in operations[consumed:]:
            if hasattr(operation, "close"):
                operation.close()


async def complete_profile(client: AtlasClient, request: ProfileArguments) -> dict[str, Any]:
    result = await profile(client, request, include_selection_meta=True)
    if any(s["next_page_token"] is not None for s in result["selections"]):
        raise RetrievalError("EVIDENCE_INCOMPLETE")
    if any(
        not s["observations"] and not s["availability"].get("release_id")
        for s in result["selections"]
    ):
        raise RetrievalError("EVIDENCE_INCOMPLETE")
    if not result["meta"]["release_id"]:
        raise RetrievalError("EVIDENCE_INCOMPLETE")
    return result


async def compare(client: AtlasClient, request: CompareArguments) -> dict[str, Any]:
    profiles = await bounded(
        [
            complete_profile(
                client, ProfileArguments(county_fips=county, selections=request.selections)
            )
            for county in request.county_fips
        ]
    )
    release = same_release([p["meta"] for p in profiles], "release_id")
    matrix = []
    for i, selection in enumerate(request.selections):
        rows = [{"county_fips": p["county_fips"], **p["selections"][i]} for p in profiles]
        signatures = [
            frozenset(
                (
                    o["period_start"],
                    o["period_end"],
                    o["temporal_grain"],
                    o["unit"],
                    o["methodology_id"],
                    o["methodology_version"],
                    o["release_methodology_version"],
                    o["semantic_version"],
                )
                for o in row["observations"]
            )
            for row in rows
            if row["observations"]
        ]
        matrix.append(
            {
                "request": selection.model_dump(exclude_none=True),
                "counties": rows,
                "comparability": "incompatible" if len(set(signatures)) > 1 else "not_established",
            }
        )
    return {
        "matrix": matrix,
        "release_id": release,
        "limitations": LIMITATIONS,
        "complete": True,
        "request_id": REQUEST_ID.get(),
    }


async def priority(client: AtlasClient, request: CountiesArguments) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for county in request.county_fips:
        item = await client.get(
            "priority_availability", None, "research:Tier1CountyPriorityAvailability", county
        )
        data = item["data"]
        if item["availability"] == "UNAVAILABLE":
            if data is not None or item["reason"] != "NO_PUBLISHED_MODEL":
                raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        elif data is None or item["reason"] is not None or data["county_fips"] != county:
            raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        if data is not None:
            scores = [data[k] for k in ("priority_tier", "priority_percentile", "raw_model_score")]
            if (data["evidence_sufficiency"] == "NOT_ESTIMABLE") != all(v is None for v in scores):
                raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
            if data["evidence_sufficiency"] != "NOT_ESTIMABLE" and any(v is None for v in scores):
                raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        results.append({"county_fips": county, "availability": item})
    same_release([r["availability"] for r in results], "geography_release_id")
    published = [
        r["availability"]["data"] for r in results if r["availability"]["data"] is not None
    ]
    if published:
        same_release(published, "release_id")
    batches = {
        (
            d["model_version"],
            d["prediction_batch_version"],
            d["tier_policy_version"],
            d["release_id"],
        )
        for d in published
    }
    return {
        "counties": results,
        "percentile_comparison": "incompatible" if len(batches) > 1 else "not_established",
        "limitations": [
            *LIMITATIONS,
            (
                "Surveillance review priority is not predicted disease risk or "
                "incidence. Percentiles are within the published batch "
                "population; do not compare across models, batches, populations "
                "or tier policies."
            ),
        ],
        "request_id": REQUEST_ID.get(),
    }


async def scores(client: AtlasClient, request: ScoresArguments) -> dict[str, Any]:
    # CountyDetail uses the same publisher _summary as /atlas/scores; no national dump.
    metadata = await client.get("atlas_metadata", None, "research:AtlasMetadata")
    release = metadata["release_id"]
    if request.dataset_version and request.dataset_version != release:
        raise RetrievalError("RELEASE_CHANGED")
    results: list[dict[str, Any]] = []
    for county in request.county_fips:
        item = await client.get(
            "county_detail", {"dataset_version": release}, "research:CountyDetail", county
        )
        if item["fips"] != county:
            raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
        same_release([item["release"]], "release_id", release)
        if item["release"] != metadata:
            raise RetrievalError("RELEASE_CHANGED")
        results.append(item)
    return {
        "counties": results,
        "metadata": metadata,
        "limitations": [
            *LIMITATIONS,
            (
                "Publisher Atlas gap scores are distinct from Tier 1 model "
                "output. No rank is inferred. Coverage is only the requested "
                "counties returned by the publisher."
            ),
        ],
        "request_id": REQUEST_ID.get(),
    }


async def review(client: AtlasClient, request: ReviewArguments) -> dict[str, Any]:
    params: dict[str, str | int] | None = (
        {"dataset_version": request.dataset_version} if request.dataset_version else None
    )
    result = await client.get("state_review", params, "research:StateReview", request.state)
    if result["requested_state"] != request.state:
        raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
    if request.dataset_version and result["data_release_version"] != request.dataset_version:
        raise RetrievalError("RELEASE_CHANGED")
    if (result["methodology_id"], result["methodology_version"]) == (
        "atlas-county-review",
        "1.0.0",
    ):
        if result["result_state"] != "unsupported" or result["review_candidates"]:
            raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
    return {
        "review": result,
        "limitations": [
            *LIMITATIONS,
            (
                "Disabled review rules remain unsupported; unsupported is not "
                "none_stand_out or outbreak identification."
            ),
        ],
        "request_id": REQUEST_ID.get(),
    }


async def brief(client: AtlasClient, request: BriefArguments) -> dict[str, Any]:
    evidence = await complete_profile(client, request)
    observations = [o for s in evidence["selections"] for o in s["observations"]]
    if any(not o["source_id"] or not o["methodology_id"] for o in observations):
        raise RetrievalError("EVIDENCE_INCOMPLETE")
    references = sorted(
        {
            (kind, o[key])
            for o in observations
            for kind, key in [("source", "source_id"), ("methodology", "methodology_id")]
        }
    )
    # Three observation calls plus at most six source/method calls = nine calls.
    if len(references) > 6:
        raise RetrievalError("EVIDENCE_INCOMPLETE")
    resources = await bounded(
        [
            provenance(
                client,
                ProvenanceArguments(
                    reference_type=cast(Literal["source", "methodology"], kind),
                    reference_id=identifier,
                    expected_release_id=evidence["meta"]["release_id"],
                ),
            )
            for kind, identifier in references
        ]
    )
    return {
        "scope": request.model_dump(exclude_none=True),
        "evidence": evidence,
        "resources": resources,
        "reference_ids": [o["evidence"] for o in observations],
        "data_gaps": [
            {"request": s["request"], "state": state}
            for s in evidence["selections"]
            for state in (
                sorted(
                    {
                        o["value_state"]
                        for o in s["observations"]
                        if o["value_state"] not in {"OBSERVED", "ZERO"}
                    }
                )
                if s["observations"]
                else ["empty"]
            )
        ],
        "temporal_caveats": [
            (
                "Observation periods and grains remain canonical; response time "
                "is not source freshness. Cumulative evidence is not converted to "
                "annual evidence."
            )
        ],
        "limitations": LIMITATIONS,
        "complete": True,
        "request_id": REQUEST_ID.get(),
    }
