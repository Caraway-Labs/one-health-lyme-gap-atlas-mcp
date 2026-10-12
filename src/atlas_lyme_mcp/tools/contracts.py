"""MCP arguments only; scientific response schemas remain API-owned."""

from datetime import date
from typing import Annotated, Any, Literal

from lyme_gap_atlas_shared.domain import normalize_county_fips
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*$")
]
Cursor = Annotated[str, Field(strict=True, min_length=1, max_length=2048)]


class StrictArguments(ArgModelBase):
    model_config = ConfigDict(extra="forbid", strict=True)


class StrictMetadata(FuncMetadata):
    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Typed MCP arguments must not accept JSON encoded inside strings."""
        return data


class DiscoveryArguments(StrictArguments):
    indicator_id: Identifier | None = None
    page_size: int = Field(default=3, ge=1, le=5)
    page_token: Cursor | None = None
    # A measure-page continuation is bound by the API to an exact indicator.
    measure_page_token: Cursor | None = None

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
                    "not": {"anyOf": [{"required": ["start_date"]}, {"required": ["end_date"]}]},
                },
                {
                    "required": ["start_date", "end_date"],
                    "properties": {
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                    "not": {"required": ["year"]},
                },
            ]
        },
    )
    measure_id: Identifier
    year: int | None = Field(default=None, ge=1900, le=2100)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    page_token: Cursor | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_period(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if "year" in value and (
                value["year"] is None or "start_date" in value or "end_date" in value
            ):
                raise ValueError("Use a non-null year or complete dates, not both")
        return value

    @model_validator(mode="after")
    def period(self) -> "Selection":
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
    county_fips: str = Field(pattern=r"^[0-9]{5}$", min_length=5, max_length=5)
    selections: list[Selection] = Field(min_length=1, max_length=3)

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
    reference_type: Literal["source", "methodology"]
    reference_id: Identifier
    expected_release_id: Identifier
