"""Strict bounded agent-facing identity contracts, separate from evidence."""

from typing import Annotated, Any, Literal

from lyme_gap_atlas_shared.domain import normalize_county_fips
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atlas_lyme_mcp.tools.contracts import StrictArguments

Name = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[^\x00-\x1f]*[^\s\x00-\x1f][^\x00-\x1f]*$",
        json_schema_extra={"not": {"pattern": r"[\x00-\x1f]"}},
    ),
]
Fips = Annotated[str, Field(strict=True, pattern=r"^[0-9]{5}$", min_length=5, max_length=5)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GeographyRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["county_fips"],
                    "properties": {"county_fips": {"type": "string"}},
                    "not": {"anyOf": [{"required": ["county"]}, {"required": ["state"]}]},
                },
                {
                    "required": ["county", "state"],
                    "properties": {"county": {"type": "string"}, "state": {"type": "string"}},
                    "not": {"required": ["county_fips"]},
                },
            ]
        },
    )
    county_fips: Fips | None = None
    county: Name | None = None
    state: Name | None = None

    @model_validator(mode="before")
    @classmethod
    def representation(cls, value: Any) -> Any:
        if isinstance(value, dict):
            keys = set(value)
            if keys not in ({"county_fips"}, {"county", "state"}) or any(
                item is None for item in value.values()
            ):
                raise ValueError("Use exactly county_fips or county and state")
        return value

    @field_validator("county", "state")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError("Names must be nonblank and contain no control characters")
        return value

    @field_validator("county_fips")
    @classmethod
    def fips(cls, value: str | None) -> str | None:
        return normalize_county_fips(value) if value is not None else None


class GeographyArguments(StrictArguments):
    geographies: list[GeographyRequest] = Field(
        min_length=1,
        max_length=4,
        description=(
            "Required array of 1–4 county references, each using exactly county_fips OR "
            "county plus state. Results preserve input order and duplicates. Names are "
            "resolved conservatively against the CDC/ATSDR SVI 2022 US states/DC reference; "
            "ambiguous matches require agent/user clarification, never automatic choice. "
            "Identity does not establish evidence availability or current legal boundaries. "
        ),
    )


class Geography(StrictModel):
    geography_type: Literal["county"] = "county"
    county_fips: Fips
    county_name: Name
    state_name: Name
    state_abbreviation: str = Field(pattern=r"^[A-Z]{2}$", min_length=2, max_length=2)
    state_fips: str = Field(pattern=r"^[0-9]{2}$", min_length=2, max_length=2)


class Reference(StrictModel):
    source: str = Field(
        max_length=512,
        description="Publisher URL of the approved CDC/ATSDR SVI 2022 county identity reference.",
    )
    version: str = Field(
        max_length=128,
        description=(
            "Fixed SVI 2022 identity vintage, not current legal boundaries or an Atlas release."
        ),
    )
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "SHA-256 of the sorted retrieved identity projection; not the Data "
            "GeoJSON artifact checksum."
        ),
    )
    retrieved_at: str = Field(
        max_length=64,
        description=(
            "Actual UTC reference retrieval time, not scientific evidence freshness"
            " or response time."
        ),
    )


class GeographyResult(StrictModel):
    input_index: int = Field(
        ge=0,
        le=3,
        description=(
            "Zero-based position in the original input batch; duplicates retain separate positions."
        ),
    )
    requested: GeographyRequest = Field(
        description=(
            "Original supplied county reference, preserving the requested representation and text."
        )
    )
    status: Literal["resolved", "ambiguous", "not_found", "unavailable"] = Field(
        description=(
            "resolved: one reference identity; ambiguous: multiple matches, "
            "requiring clarification without automatic choice; not_found: no match "
            "in the valid reference; unavailable: reference retrieval or validation"
            " failed. None establishes Atlas observation availability."
        )
    )
    geography: Geography | None = Field(
        default=None,
        description=(
            "Canonical identity only for a resolved match; null for other outcomes."
            " Membership is in the fixed 2022 reference."
        ),
    )
    candidates: list[Geography] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "At most four ambiguity candidate previews, potentially incomplete; "
            "never automatically select a candidate."
        ),
    )
    reason: Literal["AMBIGUOUS", "NOT_FOUND", "REFERENCE_UNAVAILABLE"] | None = Field(
        default=None,
        description=(
            "Categorical explanation for an unresolved item; null for resolved "
            "identity. Reference failure is distinct from no match."
        ),
    )


class GeographyResults(StrictModel):
    results: list[GeographyResult] = Field(
        min_length=1,
        max_length=4,
        description=(
            "One outcome per input in original order, including duplicates and "
            "unresolved items; inspect every status."
        ),
    )
    reference: Reference | None = Field(
        description=(
            "Shared approved identity reference provenance; null when unavailable. "
            "Identity resolution does not establish scientific observation "
            "coverage."
        )
    )


def geography_input_schema() -> dict[str, Any]:
    """Describe input-only fields without changing the shared requested output schema."""
    schema = GeographyArguments.model_json_schema()
    properties = schema["$defs"]["GeographyRequest"]["properties"]
    descriptions = {
        "county_fips": (
            "Exact five-digit ASCII county FIPS string, preserving leading zeros (for "
            "example 01001). Supply this alone for FIPS lookup; omit county and state. No "
            "zero padding or numeric coercion occurs. Omit this field entirely for "
            "county/state lookup; explicit null is invalid. "
        ),
        "county": (
            "County name, nonblank and at most 128 characters without control characters. "
            "Supply with state and omit county_fips. Case and whitespace are normalized and "
            "the County suffix is optional; other county equivalents need the full name "
            "(for example Baltimore city). No fuzzy matching or city/ZIP geocoding; "
            "ambiguous results require clarification. Omit entirely for FIPS lookup; null "
            "is invalid. "
        ),
        "state": (
            "US state name or two-letter postal abbreviation (including DC), nonblank and "
            "at most 128 characters without control characters. Required with county to "
            "disambiguate names; case and whitespace are normalized. Omit entirely with "
            "county_fips; null is invalid. Territories are outside the reference scope. "
        ),
    }
    for name, description in descriptions.items():
        properties[name]["description"] = description
    return schema
