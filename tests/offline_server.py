"""Test-only HTTP runner: production app with a controlled local identity reference.

No fixture switch or test dependency is installed in the production image.
"""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from atlas_lyme_mcp.application.client import AtlasClient
from atlas_lyme_mcp.application.geographies import SOURCE, VERSION, GeographyResolver
from atlas_lyme_mcp.application.public_schema import DOCUMENT
from atlas_lyme_mcp.server import main
from atlas_lyme_mcp.tools.geography_contracts import Geography, Reference


def fixture_resolver() -> GeographyResolver:
    resolver = GeographyResolver()
    resolver.cached = (
        [
            Geography(
                county_fips="01001",
                county_name="Autauga County",
                state_name="Alabama",
                state_abbreviation="AL",
                state_fips="01",
            )
        ],
        Reference(
            source=SOURCE,
            version=VERSION,
            sha256="a" * 64,
            retrieved_at="2026-10-17T00:00:00Z",
        ),
    )
    resolver.expires = time.monotonic() + 3600
    return resolver


def fixture_client(origin: str) -> AtlasClient:
    def load(name: str) -> dict[str, Any]:
        return dict(json.loads((Path(__file__).parent / "fixtures" / name).read_text()))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/observations"):
            page = load("public-observations.json")
            page["data"][0]["geography"]["geography_id"] = request.url.params["geography_id"]
            return httpx.Response(200, json=page)
        if path.endswith("/availability"):
            return httpx.Response(200, json=load("research-priority.json"))
        if path.endswith("/review"):
            return httpx.Response(200, json=load("research-review.json"))
        if path.endswith("/metadata"):
            return httpx.Response(200, json=load("research-metadata.json"))
        if path == "/v1/counties/09110":
            return httpx.Response(200, json=load("research-county.json"))
        if "/sources/" in path:
            return httpx.Response(200, json=load("public-source.json"))
        if "/methodologies/" in path:
            # Clearly synthetic resource matching the offline observation fixture.
            schema = DOCUMENT["components"]["schemas"]["Methodology"]
            method: dict[str, Any] = {key: None for key in schema["required"]}
            for key, value in schema["properties"].items():
                if value.get("type") == "string":
                    method[key] = "synthetic offline fixture"
                if value.get("type") == "array":
                    method[key] = []
            method.update(
                methodology_id=path.rsplit("/", 1)[1],
                release_version=load("public-source.json")["data"]["release_version"],
            )
            return httpx.Response(200, json={"data": method})
        raise AssertionError("Unapproved offline fixture route")

    return AtlasClient(origin, httpx.MockTransport(handler))


if __name__ == "__main__":
    with (
        patch("atlas_lyme_mcp.server.GeographyResolver", fixture_resolver),
        patch("atlas_lyme_mcp.server.AtlasClient", fixture_client),
    ):
        main()
