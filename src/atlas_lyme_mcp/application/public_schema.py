"""Validate unchanged public API evidence against pinned canonical OpenAPI components."""

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

DOCUMENT = json.loads(
    (Path(__file__).parents[1] / "contracts" / "public-api-schema.json").read_text()
)


RESEARCH_DOCUMENT = json.loads(
    (Path(__file__).parents[1] / "contracts" / "research-api-schema.json").read_text()
)
CONTEXT_DOCUMENT = json.loads(
    (Path(__file__).parents[1] / "contracts" / "context-api-schema.json").read_text()
)


def context_components() -> dict[str, Any]:
    """Namespace canonical context components without altering dated contracts."""
    encoded = json.dumps(CONTEXT_DOCUMENT["components"]["schemas"])
    encoded = encoded.replace("#/components/schemas/", "#/components/schemas/Context_")
    return {"Context_" + name: value for name, value in json.loads(encoded).items()}


def schema(name: str) -> dict[str, Any]:
    if name.startswith("context:"):
        return {
            "$ref": f"#/components/schemas/{name.split(':')[1]}",
            "components": CONTEXT_DOCUMENT["components"],
        }
    if name.startswith("research:"):
        return {
            "$ref": f"#/components/schemas/{name.split(':')[1]}",
            "components": RESEARCH_DOCUMENT["components"],
        }
    return {"$ref": f"#/components/schemas/{name}", "components": DOCUMENT["components"]}


def validate(name: str, value: Any) -> None:
    # Reviewed additive API collection availability metadata. Legacy output schemas stay frozen.
    if name == "CollectionEnvelope_Observation_":
        name = "research:" + name
    contract = copy.deepcopy(schema(name))

    def close_known_objects(node: Any) -> None:
        if isinstance(node, dict):
            # Fail closed on unreviewed response fields rather than forward a new
            # private/internal field. Keep canonical dynamic maps (e.g. strata).
            if "properties" in node and "additionalProperties" not in node:
                node["additionalProperties"] = False
            for child in node.values():
                close_known_objects(child)
        elif isinstance(node, list):
            for child in node:
                close_known_objects(child)

    close_known_objects(contract)
    Draft202012Validator(contract, format_checker=FormatChecker()).validate(value)
