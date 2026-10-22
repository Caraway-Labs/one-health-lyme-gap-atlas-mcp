"""MCP arguments only; scientific response schemas remain API-owned."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any, Literal

from lyme_gap_atlas_shared.domain import normalize_county_fips
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from atlas_lyme_mcp.application.telemetry import record

Identifier = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*$",
        description=(
            "Exact published Atlas identifier, 1–128 ASCII characters; starts with a letter "
            "or digit and otherwise permits letters, digits, underscore, period, colon, @ "
            "and hyphen. Supply an ID from Atlas evidence or discovery, never a URL or "
            "display name. "
        ),
    ),
]
Cursor = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=2048,
        description=(
            "Opaque API continuation token, 1–2048 characters. Copy unchanged from the "
            "matching response; never construct, edit, or reuse for another query or "
            "release. Omit to start at the first page. "
        ),
    ),
]

# Published API selection contracts, not inferred observation periods.
CONTEXT_VINTAGES = {
    "population_2022": 2022,
    "svi_percentile_2022": 2022,
    "uninsured_percent_2022": 2022,
    "uninsured_percentile_2022": 2022,
    "rucc_2023": 2023,
}
CUMULATIVE_MEASURES = {"scapularis_status", "burgdorferi_status"}


class StrictArguments(ArgModelBase):
    model_config = ConfigDict(extra="forbid", strict=True)


class StrictMetadata(FuncMetadata):
    tool_name: str = "unknown"

    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            return super().validate_arguments(arguments_to_validate)
        except ValidationError:
            record(
                "mcp_tool",
                self.tool_name,
                "INVALID_REQUEST",
                "invalid_input",
                int((time.monotonic() - started) * 1000),
            )
            raise

    async def call_fn(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        fn_is_async: bool,
        arguments: dict[str, Any],
        arguments_to_pass_directly: dict[str, Any] | None = None,
    ) -> Any:
        started = time.monotonic()
        outcome, reason = "OK", "completed"
        try:
            result = await super().call_fn(fn, fn_is_async, arguments, arguments_to_pass_directly)
            if isinstance(result, CallToolResult) and result.is_error:
                payload = result.structured_content or {}
                outcome = str(payload.get("code", "UNEXPECTED_ERROR"))
                reason = str(payload.get("reason", "retrieval_failed"))
            return result
        except asyncio.CancelledError:
            outcome, reason = "CANCELLED", "cancelled"
            raise
        except Exception:
            outcome, reason = "UNEXPECTED_ERROR", "unexpected_error"
            raise
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            if outcome == "OK" and duration_ms > 20000:
                outcome, reason = "LATE_COMPLETION", "tool_deadline"
            record(
                "mcp_tool",
                self.tool_name,
                outcome,
                reason,
                duration_ms,
            )

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Typed MCP arguments must not accept JSON encoded inside strings."""
        return data


class DiscoveryArguments(StrictArguments):
    indicator_id: Identifier | None = Field(
        default=None,
        description=(
            "Exact published indicator ID to filter discovery; omit or use null for the "
            "indicator catalog. Required with measure_page_token and must match its "
            "indicator. Use a published ID, not a display name or URL. "
        ),
    )
    page_size: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "Maximum indicators to retrieve, integer 1–5; defaults to 3. Each indicator "
            "retrieves one measure page of at most 20 measures. Preserve the original page "
            "size when continuing indicator pagination. "
        ),
    )
    page_token: Cursor | None = Field(
        default=None,
        description=(
            "Opaque indicator-page continuation from discovery meta.next_page_token. Omit "
            "or use null for the first indicator page. Reuse only with the same indicator "
            "filter, page size and release; never combine with measure_page_token or use an "
            "observation/measure cursor. "
        ),
    )
    # A measure-page continuation is bound by the API to an exact indicator.
    measure_page_token: Cursor | None = Field(
        default=None,
        description=(
            "Opaque measure-page continuation from discovery meta.measure_page_tokens for "
            "the exact indicator_id supplied alongside it. Omit or use null for the first "
            "measure page. Excludes page_token; do not reuse across indicators, queries or "
            "releases. "
        ),
    )

    @model_validator(mode="after")
    def cursor_selection(self) -> "DiscoveryArguments":
        if self.measure_page_token and (not self.indicator_id or self.page_token):
            raise ValueError("measure_page_token requires indicator_id and excludes page_token")
        return self


class Selection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["year"],
                    "properties": {"year": {"type": "integer"}},
                    "not": {
                        "anyOf": [
                            {"required": ["start_date"]},
                            {"required": ["end_date"]},
                            {"required": ["vintage_year"]},
                        ]
                    },
                },
                {
                    "required": ["start_date", "end_date"],
                    "properties": {
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                    "not": {"anyOf": [{"required": ["year"]}, {"required": ["vintage_year"]}]},
                },
                {
                    "required": ["vintage_year"],
                    "properties": {"vintage_year": {"type": "integer"}},
                    "not": {
                        "anyOf": [
                            {"required": ["year"]},
                            {"required": ["start_date"]},
                            {"required": ["end_date"]},
                        ]
                    },
                },
            ]
        },
    )
    measure_id: Identifier = Field(
        description=(
            "Exact published measure ID returned by atlas_discover_indicators; required for "
            "each selection. Use the measure ID, not its indicator ID, display name or URL. "
            "Retain its published units and time semantics. "
        )
    )
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description=(
            "Calendar year, integer 1900–2100, selecting January 1 through December 31. "
            "Supply year OR both start_date and end_date, never both representations. "
            "Omit when using vintage_year. Cumulative tick status uses exact dates "
            "2025-12-31 through 2025-12-31, not year. "
            "Omitted by default; no period is inferred. Does not convert cumulative "
            "evidence into an annual measure. "
        ),
    )
    vintage_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description=(
            "Source product/classification vintage, integer 1900-2100, distinct from an "
            "annual year. Use 2022 for population_2022 and SVI/insurance 2022 measures, "
            "or 2023 for rucc_2023. Excludes year and both date fields. Retain the "
            "publisher's reference period; ACS 2018-2022 is not a single-year observation."
        ),
    )
    start_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "Inclusive start date as a valid YYYY-MM-DD calendar date. Required with "
            "end_date when selecting dates; omit when using year or vintage_year. "
            "End must be on or after "
            "start, with at most 31 inclusive days. No date is inferred when omitted. "
        ),
    )
    end_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "Inclusive end date as a valid YYYY-MM-DD calendar date. Required with "
            "start_date when selecting dates; omit when using year or vintage_year. "
            "Must be on or after "
            "start_date and at most 30 days later (31 inclusive days). No date is inferred "
            "when omitted. "
        ),
    )
    page_token: Cursor | None = Field(
        default=None,
        description=(
            "Opaque observation continuation from this selection's next_page_token. Omit or "
            "use null for its first page (at most 31 observations). Copy unchanged and "
            "retain the same county_fips, measure_id, period and release; never use a "
            "discovery cursor or another selection's token. "
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def explicit_period(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if "vintage_year" in value and (
                value["vintage_year"] is None
                or any(k in value for k in ("year", "start_date", "end_date"))
            ):
                raise ValueError(
                    "Use a non-null vintage_year alone, excluding year and date fields"
                )
            if "year" in value and (
                value["year"] is None or "start_date" in value or "end_date" in value
            ):
                raise ValueError("Use a non-null year or complete dates, not both")
        return value

    @model_validator(mode="after")
    def period(self) -> "Selection":
        if self.measure_id in CONTEXT_VINTAGES:
            expected = CONTEXT_VINTAGES[self.measure_id]
            if self.vintage_year != expected or any(
                v is not None for v in (self.year, self.start_date, self.end_date)
            ):
                raise ValueError(
                    f"{self.measure_id} requires vintage_year={expected}; omit year and dates"
                )
            return self
        if self.vintage_year is not None:
            raise ValueError("vintage_year is supported only for published county-context measures")
        if self.measure_id in CUMULATIVE_MEASURES and (
            self.year is not None
            or self.start_date != "2025-12-31"
            or self.end_date != "2025-12-31"
        ):
            raise ValueError(
                f"{self.measure_id} is cumulative; use start_date=end_date=2025-12-31, not year"
            )
        if self.year is not None:
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("Use year or complete dates, not both")
        elif self.start_date is None or self.end_date is None:
            raise ValueError("Supply year or both start_date and end_date")
        else:
            start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
            if not 0 <= (end - start).days <= 30:
                raise ValueError("Date ranges must be ordered and cover at most 31 days")
        return self


class ProfileArguments(StrictArguments):
    county_fips: str = Field(
        pattern=r"^[0-9]{5}$",
        min_length=5,
        max_length=5,
        description=(
            "Required exact five-digit ASCII county FIPS string, preserving leading zeros "
            "(for example 01001). Do not pass a number, whitespace-padded or short code, "
            "or county name. "
            "Resolve county/state names with atlas_resolve_geographies first; no county "
            "name inference or zero padding occurs here. "
        ),
    )
    selections: list[Selection] = Field(
        min_length=1,
        max_length=3,
        description=(
            "Required array of 1–3 unique published measure/period selections for this "
            "county. Each needs measure_id and either vintage_year, year or both inclusive dates "
            "(maximum "
            "31 days). Duplicate measure-period pairs are rejected regardless of cursor. "
            "Periods remain independent and do not establish scientific comparability. "
        ),
    )

    @field_validator("county_fips")
    @classmethod
    def fips(cls, value: str) -> str:
        return normalize_county_fips(value)

    @model_validator(mode="after")
    def unique_selections(self) -> "ProfileArguments":
        keys = [s.model_dump_json(exclude={"page_token"}) for s in self.selections]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate measure-period selections")
        return self


class ProvenanceArguments(StrictArguments):
    reference_type: Literal["source", "methodology"] = Field(
        description=(
            "Required reference kind: source resolves publisher/source metadata; "
            "methodology resolves an exact methodology/version reference. Choose the kind "
            "matching the published evidence reference; this is not observation-ID lookup. "
        )
    )
    reference_id: Identifier = Field(
        description=(
            "Required exact published source_id or methodology_id matching reference_type, "
            "copied from Atlas evidence/discovery. Preserve the full identifier including "
            "any version; do not supply a title, URL, observation ID or guessed reference. "
        )
    )
    expected_release_id: Identifier = Field(
        description=(
            "Required release ID from the evidence or discovery response being cited. The "
            "resolved resource must belong to this current release or the tool fails with "
            "RELEASE_CHANGED. Guards release consistency; does not select a historical "
            "release. Refresh evidence after a release change. "
        )
    )
