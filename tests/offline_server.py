"""Test-only HTTP runner: production app with a controlled local identity reference.

No fixture switch or test dependency is installed in the production image.
"""

import time
from unittest.mock import patch

from atlas_lyme_mcp.application.geographies import SOURCE, VERSION, GeographyResolver
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


if __name__ == "__main__":
    with patch("atlas_lyme_mcp.server.GeographyResolver", fixture_resolver):
        main()
