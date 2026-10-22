"""Comparison scheduling interleaves counties without changing result ordering."""

import asyncio
from typing import Any

import pytest

from atlas_lyme_mcp.application import research
from atlas_lyme_mcp.application.client import AtlasClient
from atlas_lyme_mcp.tools.contracts import ProfileArguments, Selection
from atlas_lyme_mcp.tools.research_contracts import CompareArguments


def test_counties_share_first_wave_and_results_retain_selection_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        first_counties: set[str] = set()
        both_started = asyncio.Event()
        active = peak = 0

        async def profile(client: AtlasClient, request: ProfileArguments) -> dict[str, Any]:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            selection = request.selections[0]
            try:
                if selection.measure_id == "first":
                    first_counties.add(request.county_fips)
                    if len(first_counties) == 2:
                        both_started.set()
                # No later selection can complete before both counties start
                # the first selection. County-major scheduling deadlocks here.
                await both_started.wait()
                await asyncio.sleep(0)
                return {
                    "selections": [
                        {
                            "request": selection.model_dump(exclude_none=True),
                            "observations": [],
                            "retrieval_state": "empty",
                            "next_page_token": None,
                            "availability": {"release_id": "release"},
                        }
                    ],
                    "meta": {"release_id": "release", "response_at": selection.measure_id},
                }
            finally:
                active -= 1

        monkeypatch.setattr(research, "complete_profile", profile)
        request = CompareArguments(
            county_fips=["42029", "42091"],
            selections=[Selection(measure_id=m, year=2025) for m in ("first", "second", "third")],
        )
        result = await asyncio.wait_for(
            research.compare(AtlasClient("https://api.onehealthatlas.org"), request), 5
        )
        assert peak == 3 and active == 0
        assert result["complete"] is True
        assert [row["request"]["measure_id"] for row in result["matrix"]] == [
            "first",
            "second",
            "third",
        ]
        for row in result["matrix"]:
            assert [county["county_fips"] for county in row["counties"]] == ["42029", "42091"]
            assert all(county["request"] == row["request"] for county in row["counties"])

    asyncio.run(check())
