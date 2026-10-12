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
    geographies: list[GeographyRequest] = Field(min_length=1, max_length=4)


class Geography(StrictModel):
    geography_type: Literal["county"] = "county"
    county_fips: Fips
    county_name: Name
    state_name: Name
    state_abbreviation: str = Field(pattern=r"^[A-Z]{2}$", min_length=2, max_length=2)
    state_fips: str = Field(pattern=r"^[0-9]{2}$", min_length=2, max_length=2)


class Reference(StrictModel):
    source: str = Field(max_length=512)
    version: str = Field(max_length=128)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: str = Field(max_length=64)


class GeographyResult(StrictModel):
    input_index: int = Field(ge=0, le=3)
    requested: GeographyRequest
    status: Literal["resolved", "ambiguous", "not_found", "unavailable"]
    geography: Geography | None = None
    candidates: list[Geography] = Field(default_factory=list, max_length=4)
    reason: Literal["AMBIGUOUS", "NOT_FOUND", "REFERENCE_UNAVAILABLE"] | None = None


class GeographyResults(StrictModel):
    results: list[GeographyResult] = Field(min_length=1, max_length=4)
    reference: Reference | None
