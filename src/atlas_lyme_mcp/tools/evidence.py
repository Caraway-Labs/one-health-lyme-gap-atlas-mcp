"""Thin semantic MCP adapters over the approved shared/service boundaries."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from jsonschema import Draft202012Validator, ValidationError
from mcp.server.mcpserver.tools.base import Tool
from mcp_types import CallToolResult, TextContent, ToolAnnotations

from atlas_lyme_mcp.application import evidence
from atlas_lyme_mcp.application.client import MAX_BYTES, REQUEST_ID, AtlasClient, RetrievalError
from atlas_lyme_mcp.application.public_schema import DOCUMENT
from atlas_lyme_mcp.tools.contracts import (
    DiscoveryArguments,
    ProfileArguments,
    ProvenanceArguments,
    Selection,
    StrictArguments,
    StrictMetadata,
)

logger = logging.getLogger(__name__)


def output_schema(name: str) -> dict[str, Any]:
    def array(model: str, maximum: int) -> dict[str, Any]:
        return {
            "type": "array",
            "maxItems": maximum,
            "items": {"$ref": f"#/components/schemas/{model}"},
        }

    meta: dict[str, Any] = {"type": "object", "required": ["release_id"]}
    properties: dict[str, Any]
    if name == "atlas_discover_indicators":
        properties = {
            "indicators": array("Indicator", 5),
            "measures": array("Measure", 100),
            "meta": meta,
        }
    elif name == "atlas_get_county_profile":
        properties = {
            "county_fips": {"type": "string", "pattern": "^[0-9]{5}$"},
            "selections": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "required": ["request", "observations", "retrieval_state", "next_page_token"],
                    "properties": {
                        "observations": array("Observation", 31),
                        "retrieval_state": {"enum": ["returned", "empty"]},
                    },
                },
            },
            "meta": meta,
        }
    else:
        properties = {
            "reference_type": {"enum": ["source", "methodology"]},
            "reference_id": {"type": "string"},
            "resource": {
                "oneOf": [
                    {"$ref": "#/components/schemas/Source"},
                    {"$ref": "#/components/schemas/Methodology"},
                ]
            },
            "meta": meta,
        }

    # Annotation-only declarations preserve the complete previously accepted value set.
    # Scientific component schemas below remain opaque, pinned API-owned definitions.
    def describe(node: dict[str, Any], text: str) -> None:
        node["description"] = text

    meta["description"] = (
        "Release lineage for this bounded result. Matching releases do not establish "
        "scientific comparability or complete evidence coverage."
    )
    meta["properties"] = {
        "release_id": {
            "description": (
                "Release identity derived from returned resources; null when unknown, "
                "including all-empty discovery or county selections. No historical snapshot "
                "is implied. Provenance success matches the requested expected_release_id."
            )
        }
    }
    if name != "atlas_get_evidence_provenance":
        meta["properties"]["response_at"] = {
            "description": (
                "API response timestamp, not source freshness or source retrieval time. "
                "For county profiles this is the last selection page response timestamp; "
                "an unknown/null timestamp supplies no freshness evidence."
            )
        }
    continuation = (
        "Opaque continuation for this bounded page; null means no further page is "
        "advertised for this query. Successful execution alone does not mean all pages "
        "have been retrieved. Preserve query and release when continuing."
    )
    if name == "atlas_discover_indicators":
        describe(
            properties["indicators"],
            "Bounded page of published indicators, not actual county observation availability.",
        )
        describe(
            properties["measures"],
            "Related measures: one bounded page per returned indicator, not evidence coverage.",
        )
        meta["properties"]["next_page_token"] = {
            "description": continuation + " Supply as page_token for indicator continuation."
        }
        meta["properties"]["measure_page_tokens"] = {
            "description": (
                "Map of indicator IDs to advertised measure continuations. Continue each "
                "entry with indicator_id and measure_page_token. An empty map advertises "
                "no additional measure pages for these indicators; also inspect the "
                "indicator next_page_token before considering discovery exhausted."
            )
        }
    elif name == "atlas_get_county_profile":
        describe(
            properties["county_fips"],
            "Exact requested five-digit county FIPS, retaining leading zeros.",
        )
        describe(
            properties["selections"],
            (
                "Ordered independent measure-period results; shared release does not "
                "prove comparability."
            ),
        )
        fields = properties["selections"]["items"]["properties"]
        fields["request"] = {
            "description": (
                "Echoed measure-period selection including its supplied continuation, with "
                "absent/null optional arguments omitted; no period or measure is inferred."
            )
        }
        fields["next_page_token"] = {
            "description": continuation
            + (" Supply as this selection's page_token with the same county, measure and period.")
        }
        describe(
            fields["observations"],
            "Unchanged canonical API observations on this page, including null scientific values.",
        )
        describe(
            fields["retrieval_state"],
            "returned means at least one observation, even if its scientific value is null; "
            "empty means no observations on this selection page, never zero disease incidence "
            "or biological absence. Preserve API zero, missingness, suppression and"
            " unavailable states.",
        )
    else:
        describe(
            properties["reference_type"],
            "Requested reference kind: source resource or methodology resource.",
        )
        describe(
            properties["reference_id"],
            "Exact requested source_id or methodology_id, matched against the returned resource.",
        )
        describe(
            properties["resource"],
            "Unchanged API source or methodology resource. Provenance alone does not establish "
            "the underlying observation; retain original evidence. Null resource "
            "timestamps remain unknown.",
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
        "components": DOCUMENT["components"],
    }


class EvidenceTools:
    def __init__(self, client: AtlasClient) -> None:
        self.client = client
        self.active = 0

    async def invoke(self, name: str, operation: Awaitable[dict[str, Any]]) -> CallToolResult:
        start = time.monotonic()
        code = "OK"
        if self.active >= 3:
            # Do not queue expensive work; the coroutine has not started.
            if hasattr(operation, "close"):
                operation.close()
            return self.failure(RetrievalError("RATE_LIMITED", True, 1))
        self.active += 1
        try:
            async with asyncio.timeout(20):
                value = await operation
                Draft202012Validator(output_schema(name)).validate(value)
                encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode()) > MAX_BYTES:
                    raise RetrievalError("RESULT_TOO_LARGE")
                return CallToolResult(
                    content=[TextContent(type="text", text=encoded)], structured_content=value
                )
        except RetrievalError as error:
            code = error.code
            return self.failure(error)
        except TimeoutError:
            code = "UPSTREAM_UNAVAILABLE"
            return self.failure(RetrievalError(code, True))
        except (ValidationError, ValueError, TypeError, KeyError):
            code = "UPSTREAM_CONTRACT_INVALID"
            return self.failure(RetrievalError(code))
        finally:
            self.active -= 1
            # No request arguments, upstream bodies, IPs or source text in telemetry.
            logger.info(
                "tool=%s outcome=%s request_id=%s duration_ms=%d",
                name,
                code,
                REQUEST_ID.get(),
                int((time.monotonic() - start) * 1000),
            )

    @staticmethod
    def failure(error: RetrievalError) -> CallToolResult:
        value = {
            "code": error.code,
            "message": "Atlas evidence request could not be completed.",
            "retryable": error.retryable,
            "request_id": REQUEST_ID.get(),
        }
        if error.retry_after_seconds is not None:
            value["retry_after_seconds"] = error.retry_after_seconds
        return CallToolResult(
            is_error=True,
            content=[TextContent(type="text", text=json.dumps(value))],
            structured_content=value,
        )

    def registered(self) -> list[Tool]:
        async def atlas_discover_indicators(
            indicator_id: str | None = None,
            page_size: int = 3,
            page_token: str | None = None,
            measure_page_token: str | None = None,
        ) -> CallToolResult:
            """Discover published Atlas indicators and associated measures, preserving units,
            denominators, geography/time semantics, versions and limitations. Discovery is
            not county availability. Continue indicator pages with page_token; continue a
            measure page with indicator_id and its measure_page_tokens entry."""
            request = DiscoveryArguments(
                indicator_id=indicator_id,
                page_size=page_size,
                page_token=page_token,
                measure_page_token=measure_page_token,
            )
            return await self.invoke(
                "atlas_discover_indicators", evidence.discover(self.client, request)
            )

        async def atlas_get_county_profile(
            county_fips: str, selections: list[Selection]
        ) -> CallToolResult:
            """Retrieve published evidence for one exact five-digit county FIPS and 1–3 explicit
            measure-period selections (year OR inclusive dates, max 31 days). Preserve values,
            missingness, units and provenance. Independent periods do not establish scientific
            comparability. No scores, inferred county names, risk or biological absence claims.
            Continue a selection using its next_page_token with the same county/measure/period."""
            request = ProfileArguments(county_fips=county_fips, selections=selections)
            return await self.invoke(
                "atlas_get_county_profile", evidence.profile(self.client, request)
            )

        async def atlas_get_evidence_provenance(
            reference_type: Literal["source", "methodology"],
            reference_id: str,
            expected_release_id: str,
        ) -> CallToolResult:
            """Resolve a published source or exact methodology reference for the expected
            current release. Keep publisher/update/retrieval timestamps and limitations;
            null timestamps remain unknown. Retain the original observation to cite evidence.
            Historical or arbitrary observation-ID lookup is not supported."""
            request = ProvenanceArguments(
                reference_type=reference_type,
                reference_id=reference_id,
                expected_release_id=expected_release_id,
            )
            return await self.invoke(
                "atlas_get_evidence_provenance", evidence.provenance(self.client, request)
            )

        specs: list[tuple[Callable[..., Any], type[StrictArguments]]] = [
            (atlas_discover_indicators, DiscoveryArguments),
            (atlas_get_county_profile, ProfileArguments),
            (atlas_get_evidence_provenance, ProvenanceArguments),
        ]
        tools = []
        for function, arguments in specs:
            tool = Tool.from_function(
                function,
                annotations=ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=True,
                ),
            )
            # SDK-supported Tool metadata: strict flat args, not permissive inferred kwargs.
            tool.fn_metadata = StrictMetadata(
                arg_model=arguments, output_schema=output_schema(tool.name)
            )
            tool.parameters = arguments.model_json_schema()
            tools.append(tool)
        return tools
