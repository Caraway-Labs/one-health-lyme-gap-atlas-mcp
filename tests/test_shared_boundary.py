"""Lock and import guards for the portable Atlas shared-domain boundary."""

import ast
import importlib.metadata
import importlib.util
import json
import tomllib
from pathlib import Path

import pytest
from lyme_gap_atlas_shared.domain import normalize_county_fips
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
SHARED_SHA = "83ccbe76047185f6aacaff551afd8b03d88aa5cf"
FORBIDDEN = (
    "lyme_gap_atlas_shared.infrastructure",
    "lyme_gap_atlas_shared.snowflake",
    "lyme_gap_atlas_shared.settings",
    "snowflake",
    "neo4j",
    "pydantic_settings",
)


def _forbidden(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN)


def test_portable_county_identifier_contract() -> None:
    assert normalize_county_fips("01001") == "01001"
    for ambiguous in ("1001", " 01001", "01001 ", "0100A"):
        with pytest.raises(ValueError):
            normalize_county_fips(ambiguous)


def test_production_imports_exclude_persistence() -> None:
    source = ROOT / "src" / "atlas_lyme_mcp"
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                if node.module == "lyme_gap_atlas_shared":
                    names.extend(f"lyme_gap_atlas_shared.{alias.name}" for alias in node.names)
            else:
                continue
            assert not any(_forbidden(name) for name in names), (path, names)


def test_shared_base_is_immutable_and_has_no_persistence_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency = [
        Requirement(item)
        for item in project["project"]["dependencies"]
        if Requirement(item).name == "one-health-lyme-gap-atlas-shared"
    ]
    assert len(dependency) == 1
    assert not dependency[0].extras
    assert dependency[0].url == (
        "git+https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-shared-python.git@"
        + SHARED_SHA
    )

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    shared = next(p for p in lock["package"] if p["name"] == dependency[0].name)
    assert shared["version"] == "1.0.0"
    assert shared["source"]["git"].endswith("#" + SHARED_SHA)
    assert {item["name"] for item in shared["dependencies"]} == {"pydantic"}

    installed = importlib.metadata.distribution(dependency[0].name)
    assert installed.version == "1.0.0"
    direct_url = installed.read_text("direct_url.json")
    assert direct_url is not None
    assert json.loads(direct_url)["vcs_info"]["commit_id"] == SHARED_SHA
    base_requires = {
        Requirement(item).name
        for item in installed.requires or []
        if Requirement(item).marker is None
    }
    assert base_requires == {"pydantic"}
    for package in ("snowflake", "neo4j", "pydantic_settings"):
        assert importlib.util.find_spec(package) is None
