"""Research tool registration and documented, bounded output contracts."""

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.tools.base import Tool
from mcp_types import CallToolResult, ToolAnnotations

from atlas_lyme_mcp.application import research
from atlas_lyme_mcp.application.public_schema import DOCUMENT, RESEARCH_DOCUMENT
from atlas_lyme_mcp.tools.contracts import Selection, StrictArguments, StrictMetadata
from atlas_lyme_mcp.tools.evidence import EvidenceTools
from atlas_lyme_mcp.tools.research_contracts import (
    BriefArguments,
    CompareArguments,
    CountiesArguments,
    ReviewArguments,
    ScoresArguments,
)


def output_schema(name: str) -> dict[str, Any]:
    def ref(n: str) -> dict[str, Any]:
        return {"$ref": "#/components/schemas/" + n}

    def array(item: dict[str, Any], maximum: int) -> dict[str, Any]:
        return {"type": "array", "maxItems": maximum, "items": item}

    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        }

    text = {"type": "string"}
    limitations = array(text, 20)
    selection_result = obj(
        {
            "request": Selection.model_json_schema(),
            "observations": array(ref("Observation"), 31),
            "retrieval_state": {"enum": ["returned", "empty"]},
            "next_page_token": {"type": "null"},
            "availability": ref("CollectionMeta"),
        }
    )
    profile = obj(
        {
            "county_fips": text,
            "selections": array(selection_result, 3),
            "meta": obj(
                {"release_id": text, "response_at": {"type": "string", "format": "date-time"}}
            ),
        }
    )
    props: dict[str, Any] = {"limitations": limitations, "request_id": text}
    if name == "atlas_compare_counties":
        row = {
            **selection_result,
            "required": [*selection_result["required"], "county_fips"],
            "properties": {**selection_result["properties"], "county_fips": text},
        }
        props |= {
            "matrix": array(
                obj(
                    {
                        "request": Selection.model_json_schema(),
                        "counties": array(row, 5),
                        "comparability": {"enum": ["incompatible", "not_established"]},
                    }
                ),
                3,
            ),
            "release_id": text,
            "complete": {"const": True},
        }
    elif name == "atlas_get_surveillance_priority":
        props |= {
            "counties": array(
                obj({"county_fips": text, "availability": ref("Tier1CountyPriorityAvailability")}),
                5,
            ),
            "percentile_comparison": {"enum": ["incompatible", "not_established"]},
        }
    elif name == "atlas_get_atlas_scores":
        props |= {"counties": array(ref("CountyDetail"), 5), "metadata": ref("AtlasMetadata")}
    elif name == "atlas_review_state":
        props |= {"review": ref("StateReview")}
    elif name == "atlas_build_evidence_brief":
        provenance = obj(
            {
                "reference_type": {"enum": ["source", "methodology"]},
                "reference_id": text,
                "resource": {"oneOf": [ref("Source"), ref("Methodology")]},
                "meta": obj({"release_id": text}),
            }
        )
        scope = BriefArguments.model_json_schema()
        props |= {
            "scope": scope,
            "evidence": profile,
            "resources": array(provenance, 6),
            "reference_ids": array(ref("EvidenceReference"), 93),
            "data_gaps": array(
                obj(
                    {
                        "request": Selection.model_json_schema(),
                        "state": {
                            "enum": [
                                "empty",
                                "MISSING",
                                "SUPPRESSED",
                                "UNAVAILABLE",
                                "NO_RECORDS",
                                "NO_COUNTY_LINKED_RECORD",
                            ]
                        },
                    }
                ),
                21,
            ),
            "temporal_caveats": array(text, 5),
            "complete": {"const": True},
        }
    else:
        raise ValueError("Unknown research tool")
    descriptions = {
        "limitations": (
            "Interpretation limits; retain each publisher limitation in canonical resources too."
        ),
        "request_id": (
            "Transport request identifier propagated to approved REST calls for reproducibility."
        ),
        "matrix": (
            "One row group per requested measure period, with original county "
            "observations and explicit coverage."
        ),
        "counties": (
            "Only the explicitly requested counties, preserving publisher "
            "data and identity without inferred ranks."
        ),
        "comparability": (
            "Known cross-county period, grain, unit or method mismatches; "
            "not_established never asserts comparability."
        ),
        "percentile_comparison": (
            "Incompatible model, batch, policy or release identities are "
            "flagged; comparability is never inferred."
        ),
        "release_id": (
            "Exact common source release; incompatible or unknown release evidence fails closed."
        ),
        "complete": (
            "All requested first pages and required references were retrieved "
            "with no advertised continuation."
        ),
        "metadata": (
            "Unmodified publisher release metadata and methodology; this is "
            "separate from Tier 1 model lineage."
        ),
        "review": (
            "Canonical state review including disabled unsupported rules, "
            "coverage, gaps and evaluation time."
        ),
        "scope": "Exact validated request; measure periods and county identity are never inferred.",
        "evidence": (
            "Canonical bounded county observations retaining scientific "
            "values, timestamps and missingness states."
        ),
        "resources": (
            "Exact source and methodology resources from the same evidence "
            "release; no fabricated citations."
        ),
        "reference_ids": (
            "Original observation evidence references for citation, retaining "
            "release and version identifiers."
        ),
        "data_gaps": (
            "Explicit empty selections and publisher missing, suppressed, "
            "unavailable or no-record states; never biological absence."
        ),
        "temporal_caveats": (
            "Period and timestamp interpretation limits; retrieval time does "
            "not establish source freshness."
        ),
    }
    for key, value in props.items():
        value["description"] = descriptions[key]
    result = obj(props)
    result["components"] = {
        "schemas": {
            **DOCUMENT["components"]["schemas"],
            **RESEARCH_DOCUMENT["components"]["schemas"],
        }
    }
    # Pydantic nested models use root-local definitions.
    result["$defs"] = BriefArguments.model_json_schema()["$defs"]
    return result


def registered(owner: EvidenceTools) -> list[Tool]:
    async def atlas_compare_counties(
        county_fips: list[str], selections: list[Selection]
    ) -> CallToolResult:
        """Compare 2-5 counties over 1-3 exact measure-period selections. Preserve canonical values,
        missingness and provenance in a county matrix. Flag period/grain/method incompatibility;
        never rank, infer significance or claim biological absence. Incomplete pages fail closed."""
        return await owner.invoke(
            "atlas_compare_counties",
            research.compare(
                owner.client, CompareArguments(county_fips=county_fips, selections=selections)
            ),
        )

    async def atlas_get_surveillance_priority(county_fips: list[str]) -> CallToolResult:
        """Inspect persisted surveillance review priorities for 1-5 counties, preserving model,
        batch, policy, evidence sufficiency and NO_PUBLISHED_MODEL. Review priority is not disease
        risk, incidence or clinical advice; percentiles cannot be compared across populations."""
        return await owner.invoke(
            "atlas_get_surveillance_priority",
            research.priority(owner.client, CountiesArguments(county_fips=county_fips)),
        )

    async def atlas_get_atlas_scores(
        county_fips: list[str], dataset_version: str | None = None
    ) -> CallToolResult:
        """Retrieve publisher Atlas gap scores and release metadata for 1-5 exact counties using
        bounded county detail. No national collection, ranking or synthesized score. Atlas gap
        scores remain distinct from Tier 1 model output and individual disease risk."""
        return await owner.invoke(
            "atlas_get_atlas_scores",
            research.scores(
                owner.client,
                ScoresArguments(county_fips=county_fips, dataset_version=dataset_version),
            ),
        )

    async def atlas_review_state(state: str, dataset_version: str | None = None) -> CallToolResult:
        """Inspect one state's published review, methodology, release, gaps and county coverage.
        Disabled atlas-county-review rules remain unsupported, never none_stand_out or outbreak
        identification. Optional dataset version must match the publisher release."""
        return await owner.invoke(
            "atlas_review_state",
            research.review(
                owner.client, ReviewArguments(state=state, dataset_version=dataset_version)
            ),
        )

    async def atlas_build_evidence_brief(
        county_fips: str, selections: list[Selection]
    ) -> CallToolResult:
        """Assemble a structured citation-ready county brief with 1-3 explicit measure periods,
        canonical observations and source/method resources. Preserve release, reference IDs,
        gaps and temporal caveats. Incomplete pages/provenance fail closed; no fabricated citations,
        PDF, inference or clinical advice. At most nine public-service calls."""
        return await owner.invoke(
            "atlas_build_evidence_brief",
            research.brief(
                owner.client, BriefArguments(county_fips=county_fips, selections=selections)
            ),
        )

    specs: list[tuple[Callable[..., Any], type[StrictArguments]]] = [
        (atlas_compare_counties, CompareArguments),
        (atlas_get_surveillance_priority, CountiesArguments),
        (atlas_get_atlas_scores, ScoresArguments),
        (atlas_review_state, ReviewArguments),
        (atlas_build_evidence_brief, BriefArguments),
    ]
    result = []
    for fn, args in specs:
        tool = Tool.from_function(
            fn,
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=True,
            ),
        )
        tool.parameters = args.model_json_schema()
        tool.fn_metadata = StrictMetadata(arg_model=args, output_schema=output_schema(tool.name))
        result.append(tool)
    return result
