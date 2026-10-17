"""Positive and deliberately damaged client-visible metadata contracts."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from catalog_discovery import discover_catalog
from metadata_gate import schema_errors, validate_catalog

BASELINE = json.loads(
    (Path(__file__).parent / "fixtures/mcp-catalog-contract.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def catalog() -> list[dict[str, Any]]:
    return discover_catalog()


def test_serialized_catalog_quality_and_contract(catalog: list[dict[str, Any]]) -> None:
    validate_catalog(catalog, BASELINE)


@pytest.mark.parametrize(
    "tool_name,path,value,diagnostic",
    [
        ("server_status", "description", None, "server_status.description"),
        ("server_status", "description", "server_status", "unhelpful description"),
        ("server_status", "description", "Description goes here", "unhelpful description"),
        ("server_status", "name", " ", "missing nonempty tool name"),
        ("atlas_smoke_test", "name", "server_status", "duplicate tool name"),
        ("atlas_smoke_test", "name", "unexpected_tool", "unexpected tool"),
        ("server_status", "inputSchema", [], "JSON Schema object"),
        ("server_status", "inputSchema.type", "invalid", "invalid JSON Schema"),
        (
            "atlas_get_county_profile",
            "inputSchema.properties.county_fips.description",
            " \n\t",
            "atlas_get_county_profile.county_fips: missing description",
        ),
        (
            "atlas_get_county_profile",
            "inputSchema.$defs.Selection.properties.measure_id.description",
            None,
            "atlas_get_county_profile.selections[].measure_id: missing description",
        ),
        (
            "atlas_resolve_geographies",
            "inputSchema.$defs.GeographyRequest.properties.state.description",
            None,
            "atlas_resolve_geographies.geographies[].state: missing description",
        ),
        (
            "atlas_resolve_geographies",
            "inputSchema.$defs.GeographyRequest.properties.new_geography_field",
            {"type": "string"},
            "atlas_resolve_geographies.geographies[].new_geography_field: missing description",
        ),
        (
            "atlas_get_county_profile",
            "inputSchema.properties.selections.items.$ref",
            "#/$defs/Missing",
            "unresolved $ref",
        ),
        (
            "atlas_get_county_profile",
            "inputSchema.properties.selections.items.$ref",
            "https://example.invalid/schema",
            "unsupported $ref",
        ),
        ("atlas_get_county_profile", "outputSchema", None, "outputSchema"),
        ("atlas_get_county_profile", "annotations.readOnlyHint", None, "annotations.readOnlyHint"),
        (
            "atlas_get_county_profile",
            "annotations.destructiveHint",
            True,
            "annotations.destructiveHint",
        ),
        (
            "atlas_get_county_profile",
            "annotations.idempotentHint",
            False,
            "annotations.idempotentHint",
        ),
        (
            "atlas_get_county_profile",
            "annotations.openWorldHint",
            None,
            "annotations.openWorldHint",
        ),
        (
            "atlas_discover_indicators",
            "inputSchema.properties.page_size.default",
            4,
            "page_size.default: contract changed",
        ),
        (
            "atlas_discover_indicators",
            "inputSchema.properties.page_size.maximum",
            6,
            "page_size.maximum: contract changed",
        ),
        (
            "atlas_get_county_profile",
            "inputSchema.additionalProperties",
            True,
            "additionalProperties: contract changed",
        ),
        (
            "atlas_get_county_profile",
            "inputSchema.required",
            [],
            "required: contract changed",
        ),
        (
            "atlas_get_county_profile",
            "inputSchema.$defs.Selection.oneOf",
            [],
            "invalid JSON Schema",
        ),
    ],
)
def test_catalog_defects(
    catalog: list[dict[str, Any]], tool_name: str, path: str, value: Any, diagnostic: str
) -> None:
    damaged = copy.deepcopy(catalog)
    target = next(tool for tool in damaged if tool["name"] == tool_name)
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    if value is None:
        target.pop(keys[-1])
    else:
        target[keys[-1]] = value
    with pytest.raises(AssertionError) as failure:
        validate_catalog(damaged, BASELINE)
    assert diagnostic in str(failure.value)


def test_removed_tool(catalog: list[dict[str, Any]]) -> None:
    with pytest.raises(AssertionError, match="server_status: missing expected tool"):
        validate_catalog([tool for tool in catalog if tool["name"] != "server_status"])


@pytest.mark.parametrize(
    "path,value",
    [
        ("properties.county_fips.type", "integer"),
        ("properties.county_fips.minLength", 4),
        ("properties.county_fips.maxLength", 6),
        ("properties.county_fips.pattern", "^[0-9]+$"),
        ("properties.selections.minItems", 0),
        ("properties.selections.maxItems", 4),
        ("$defs.Selection.oneOf", None),
    ],
)
def test_valid_schema_contract_drift(catalog: list[dict[str, Any]], path: str, value: Any) -> None:
    damaged = copy.deepcopy(catalog)
    tool = next(t for t in damaged if t["name"] == "atlas_get_county_profile")
    target = tool["inputSchema"]
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    if value is None:
        target.pop(keys[-1])
    else:
        target[keys[-1]] = value
    with pytest.raises(AssertionError, match="contract (changed|field added or removed)"):
        validate_catalog(damaged, BASELINE)


def test_enum_and_output_drift(catalog: list[dict[str, Any]]) -> None:
    damaged = copy.deepcopy(catalog)
    tool = next(t for t in damaged if t["name"] == "atlas_get_evidence_provenance")
    tool["inputSchema"]["properties"]["reference_type"]["enum"].append("other")
    tool["outputSchema"]["description"] = "Unapproved scientific output description change."
    with pytest.raises(AssertionError) as failure:
        validate_catalog(damaged, BASELINE)
    assert "reference_type.enum: contract changed" in str(failure.value)
    assert "outputSchema: contract changed" in str(failure.value)


@pytest.mark.parametrize("keyword", ["oneOf", "anyOf", "allOf"])
def test_composition_new_properties_and_structural_repeats(keyword: str) -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"existing": {"type": "string", "description": "Existing published value."}},
        keyword: [
            {"properties": {"existing": {"type": "string"}}},
            {"properties": {"new": {"type": ["string", "null"]}}},
        ],
    }
    errors = schema_errors(schema, "example", descriptions=True)
    assert len(errors) == 1
    assert f"example.{keyword}[1].new: missing description" in errors[0]
    schema[keyword][1]["properties"]["new"]["description"] = "New optional input value."
    assert schema_errors(schema, "example", descriptions=True) == []


def test_inline_nested_arrays_nullable_and_recursive_escaped_refs() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "entries": {
                "description": "Optional nested input entries.",
                "anyOf": [
                    {"type": "null"},
                    {"type": "array", "items": {"$ref": "#/$defs/a~1b~0c"}},
                ],
            }
        },
        "$defs": {
            "a/b~c": {
                "type": "object",
                "properties": {
                    "next": {"description": "Next linked input entry.", "$ref": "#/$defs/a~1b~0c"},
                    "inline": {
                        "type": "object",
                        "description": "Inline input configuration object.",
                        "properties": {"value": {"type": "string"}},
                    },
                },
            },
            "unused": {"type": "object", "properties": {"forgotten": {"type": "boolean"}}},
        },
    }
    errors = schema_errors(schema, "example", descriptions=True)
    assert any("example.entries.anyOf[1][].inline.value: missing description" in e for e in errors)
    assert any("example.$defs.unused.forgotten: missing description" in e for e in errors)
    schema["$defs"]["a/b~c"]["properties"]["inline"]["properties"]["value"]["description"] = (
        "Explicit inline input value."
    )
    schema["$defs"]["unused"]["properties"]["forgotten"]["description"] = (
        "Enable this input option."
    )
    assert schema_errors(schema, "example", descriptions=True) == []


def test_input_prose_can_improve_without_changing_contract(catalog: list[dict[str, Any]]) -> None:
    changed = copy.deepcopy(catalog)
    changed[0]["description"] = "Improved tool description with explicit purpose."
    changed[0]["inputSchema"]["properties"]["page_size"]["description"] = (
        "Maximum number of indicators requested."
    )
    validate_catalog(changed, BASELINE)
