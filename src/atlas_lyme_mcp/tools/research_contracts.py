"""Strict bounds for the research orchestration contracts."""

from typing import Annotated

from lyme_gap_atlas_shared.domain import normalize_county_fips
from pydantic import AfterValidator, Field, model_validator

from atlas_lyme_mcp.tools.contracts import Identifier, ProfileArguments, Selection, StrictArguments

County = Annotated[
    str,
    Field(
        pattern=r"^[0-9]{5}$",
        min_length=5,
        max_length=5,
        description=(
            "Exact five ASCII-digit county FIPS; retain leading zeros and resolve names first."
        ),
    ),
    AfterValidator(normalize_county_fips),
]


class CountiesArguments(StrictArguments):
    county_fips: list[County] = Field(
        min_length=1,
        max_length=5,
        description=(
            "One to five distinct exact county FIPS; no national selection or inferred geography."
        ),
    )

    @model_validator(mode="after")
    def distinct(self) -> "CountiesArguments":
        if len(set(self.county_fips)) != len(self.county_fips):
            raise ValueError("Counties must be distinct")
        return self


class CompareArguments(CountiesArguments):
    county_fips: list[County] = Field(
        min_length=2,
        max_length=5,
        description=(
            "Two to five distinct exact county FIPS to compare without rankings or inference."
        ),
    )
    selections: list[Selection] = Field(
        min_length=1,
        max_length=3,
        description=(
            "One to three unique measure-period selections, first page only; "
            "incomplete results fail closed."
        ),
    )

    @model_validator(mode="after")
    def selections_valid(self) -> "CompareArguments":
        ProfileArguments(county_fips=self.county_fips[0], selections=self.selections)
        if any(s.page_token for s in self.selections):
            raise ValueError("Comparison starts at the first page")
        return self


class BriefArguments(ProfileArguments):
    @model_validator(mode="after")
    def first_page(self) -> "BriefArguments":
        if any(s.page_token for s in self.selections):
            raise ValueError("Brief requires first-page evidence")
        return self


class ScoresArguments(CountiesArguments):
    dataset_version: Identifier | None = Field(
        default=None,
        description=(
            "Optional exact current release ID; historical snapshot retrieval is not provided."
        ),
    )


class ReviewArguments(StrictArguments):
    state: str = Field(
        pattern=(
            "^(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|"
            "MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN"
            "|TX|UT|VT|VA|WA|WV|WI|WY)$"
        ),
        description=(
            "Exact uppercase US state or DC postal abbreviation; no inferred "
            "state or national selection."
        ),
    )
    dataset_version: Identifier | None = Field(
        default=None,
        description="Optional exact current dataset release ID; mismatching releases fail closed.",
    )
