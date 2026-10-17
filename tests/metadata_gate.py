"""Offline quality gate for decoded, client-visible tools/list JSON.

Descriptions are checked heuristically, not for scientific correctness. Contract
snapshots deliberately exclude input prose so editorial improvements stay cheap.
"""

import hashlib
import json
import re
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

EXPECTED_TOOLS = frozenset(
    {
        "server_status",
        "atlas_smoke_test",
        "atlas_discover_indicators",
        "atlas_get_county_profile",
        "atlas_get_evidence_provenance",
        "atlas_resolve_geographies",
    }
)
DOMAIN_TOOLS = EXPECTED_TOOLS - {"server_status", "atlas_smoke_test"}
ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def useful_description(value: Any, name: str) -> bool:
    if not isinstance(value, str):
        return False
    words = re.findall(r"[a-z0-9]+", value.casefold())
    normalized = " ".join(words)
    return (
        len(words) >= 3
        and len(normalized) >= 15
        and normalized not in {"description goes here", "to be documented"}
        and normalized != " ".join(re.findall(r"[a-z0-9]+", name.casefold()))
    )


def schema_errors(schema: Any, path: str, *, descriptions: bool) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return [f"{path}: must be a JSON Schema object with type=object"]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        location = ".".join(map(str, error.absolute_path))
        return [f"{path}.{location}: invalid JSON Schema: {error.message}"]
    if schema.get("type") != "object":
        return [f"{path}: must be a JSON Schema object with type=object"]

    visited: set[int] = set()

    def resolve(ref: str, location: str) -> Any:
        # Never fetch a remote schema in CI. Published contracts are self-contained.
        if ref == "#":
            return schema
        if not ref.startswith("#/"):
            errors.append(f"{location}: unsupported $ref {ref!r}; use a local JSON pointer")
            return None
        target: Any = schema
        try:
            for token in ref[2:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                target = target[int(token)] if isinstance(target, list) else target[token]
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f"{location}: unresolved $ref {ref!r}; restore its schema target")
            return None
        if not isinstance(target, (dict, bool)):
            errors.append(f"{location}: $ref {ref!r} must resolve to a schema")
            return None
        return target

    def walk(node: Any, location: str, ancestors: frozenset[int], declared: frozenset[str]) -> None:
        if not isinstance(node, dict) or id(node) in ancestors:
            return
        visited.add(id(node))
        ancestors = ancestors | {id(node)}
        if "$ref" in node:
            walk(resolve(node["$ref"], location), location, ancestors, declared)
        properties = node.get("properties", {})
        local = declared | properties.keys()
        for name, field in properties.items():
            field_path = f"{location}.{name}"
            # Constraint-only branches may repeat an already declared property.
            # A new property introduced inside a union still needs its own prose.
            description = field.get("description") if isinstance(field, dict) else None
            if descriptions and (name not in declared or description is not None):
                if not useful_description(description, name):
                    errors.append(
                        f"{field_path}: missing description or unhelpful description; "
                        "describe the input meaning and permitted use"
                    )
            walk(field, field_path, ancestors, frozenset())
        for keyword in ("oneOf", "anyOf", "allOf"):
            for index, branch in enumerate(node.get(keyword, [])):
                walk(branch, f"{location}.{keyword}[{index}]", ancestors, frozenset(local))
        if "items" in node:
            walk(node["items"], f"{location}[]", ancestors, frozenset())
        for index, item in enumerate(node.get("prefixItems", [])):
            walk(item, f"{location}[{index}]", ancestors, frozenset())
        for keyword in ("not", "if", "then", "else"):
            if keyword in node:
                walk(node[keyword], f"{location}.{keyword}", ancestors, frozenset(local))
        for keyword in (
            "additionalProperties",
            "contains",
            "propertyNames",
            "unevaluatedProperties",
        ):
            if keyword in node:
                walk(node[keyword], f"{location}.{keyword}", ancestors, frozenset())
        for keyword in ("patternProperties", "dependentSchemas"):
            for name, child in node.get(keyword, {}).items():
                walk(child, f"{location}.{keyword}.{name}", ancestors, frozenset())

    walk(schema, path, frozenset(), frozenset())

    # Also cover unused definitions. Resolve used ones first for actionable input paths.
    def definitions(node: Any, location: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in ("$defs", "definitions"):
                    for name, definition in child.items():
                        if id(definition) not in visited:
                            walk(definition, f"{location}.{key}.{name}", frozenset(), frozenset())
                definitions(child, f"{location}.{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                definitions(child, f"{location}[{index}]")

    definitions(schema, path)
    return errors


def without_input_descriptions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_input_descriptions(child)
            for key, child in value.items()
            if key != "description"
        }
    if isinstance(value, list):
        return [without_input_descriptions(child) for child in value]
    return value


def contract_projection(tools: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        tool["name"]: {
            "inputSchema": without_input_descriptions(tool["inputSchema"]),
            # Keep API-owned scientific schemas opaque and exact without copying
            # their large component document into another fixture.
            "outputSchema": hashlib.sha256(
                json.dumps(tool.get("outputSchema"), sort_keys=True).encode()
            ).hexdigest(),
            "annotations": tool.get("annotations"),
        }
        for tool in tools
    }


def differences(actual: Any, expected: Any, path: str) -> list[str]:
    if type(actual) is not type(expected):
        return [f"{path}: contract changed from {expected!r} to {actual!r}; review the contract"]
    if isinstance(expected, dict):
        errors = []
        for key in sorted(actual.keys() | expected.keys()):
            if key not in actual or key not in expected:
                errors.append(f"{path}.{key}: contract field added or removed; review the contract")
            else:
                errors.extend(differences(actual[key], expected[key], f"{path}.{key}"))
        return errors
    if actual != expected:
        return [f"{path}: contract changed from {expected!r} to {actual!r}; review the contract"]
    return []


def validate_catalog(tools: list[dict[str, Any]], baseline: dict[str, Any] | None = None) -> None:
    errors = []
    names: set[str] = set()
    for index, tool in enumerate(tools):
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"tools[{index}].name: missing nonempty tool name")
            continue
        if name in names:
            errors.append(f"{name}.name: duplicate tool name; register it only once")
        names.add(name)
        if not useful_description(tool.get("description"), name):
            errors.append(f"{name}.description: missing description or unhelpful description")
        errors.extend(schema_errors(tool.get("inputSchema"), name, descriptions=True))
        if name in DOMAIN_TOOLS:
            errors.extend(
                schema_errors(tool.get("outputSchema"), f"{name}.outputSchema", descriptions=False)
            )
            annotations = tool.get("annotations") or {}
            if not isinstance(annotations, dict):
                errors.append(f"{name}.annotations: must serialize as an object")
                continue
            for key, expected in ANNOTATIONS.items():
                if annotations.get(key) is not expected:
                    errors.append(f"{name}.annotations.{key}: must serialize as {expected!r}")
    for name in sorted(EXPECTED_TOOLS - names):
        errors.append(f"{name}: missing expected tool; restore the registration")
    for name in sorted(names - EXPECTED_TOOLS):
        errors.append(f"{name}: unexpected tool; obtain contract review before updating inventory")
    if baseline is not None and not errors:
        errors.extend(differences(contract_projection(tools), baseline, "tools"))
    if errors:
        raise AssertionError("MCP metadata quality failed:\n" + "\n".join(errors))
