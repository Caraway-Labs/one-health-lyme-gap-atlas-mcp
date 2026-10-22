"""Bounded official-SDK latency receipts, retaining successes and failures separately.

Run against a freshly started local production app to measure process-cold calls.
Remote first calls are client-cold only: this tool cannot establish API/cache state.
The whole-tool 20s and HTTP 15s limits are unchanged by this harness.
"""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp import Client

SELECTIONS = [
    {"measure_id": measure, "start_date": "2025-01-01", "end_date": "2025-01-31"}
    for measure in ("nclimgrid_tavg_county_day", "nclimgrid_prcp_county_day")
] + [{"measure_id": "nlcd_forest_area_share_county_year", "year": 2025}]
CASES: dict[str, dict[str, Any]] = {
    "atlas_discover_indicators": {"page_size": 5},
    "atlas_compare_counties": {"county_fips": ["42029", "42091"], "selections": SELECTIONS},
}


async def benchmark(url: str) -> list[dict[str, Any]]:
    receipts = []
    async with Client(url, mode="legacy") as client:
        for phase in ("first", "warm", "concurrent"):

            async def call(name: str, phase: str = phase) -> dict[str, Any]:
                started = time.monotonic()
                try:
                    result = await client.call_tool(name, CASES[name])
                    value = result.structured_content
                    complete = not result.is_error and value is not None
                    if complete and name == "atlas_compare_counties":
                        complete = (
                            value.get("complete") is True and len(value.get("matrix", [])) == 3
                        )
                        complete = complete and all(
                            [c["county_fips"] for c in row["counties"]] == ["42029", "42091"]
                            and all(c["next_page_token"] is None for c in row["counties"])
                            for row in value["matrix"]
                        )
                    return {
                        "phase": phase,
                        "tool": name,
                        "elapsed_seconds": time.monotonic() - started,
                        "success": complete,
                        "is_error": result.is_error,
                        "result": value,
                    }
                except Exception as error:
                    # Exception type only; never dump arbitrary transport text/arguments.
                    return {
                        "phase": phase,
                        "tool": name,
                        "elapsed_seconds": time.monotonic() - started,
                        "success": False,
                        "exception_type": type(error).__name__,
                    }

            if phase == "concurrent":
                batch = await asyncio.gather(*(call(name) for name in CASES))
            else:
                batch = [await call(name) for name in CASES]
            receipts.extend(batch)
            for receipt in batch:
                print(
                    phase,
                    receipt["tool"],
                    "success=" + str(receipt["success"]),
                    round(receipt["elapsed_seconds"], 3),
                    flush=True,
                )
    return receipts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    approved = args.url in {
        "https://mcp.onehealthatlas.org/mcp",
        "https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp",
    }
    local = (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port
        and parsed.path == "/mcp"
    )
    if (
        not (approved or local)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an approved MCP hostname or explicit loopback port")
    receipts = asyncio.run(benchmark(args.url))
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "endpoint": args.url,
                "source_sha": args.source_sha,
                "checks": receipts,
                "limits": {"tool_seconds": 20, "http_seconds": 15, "active_downstream": 3},
                "interpretation": (
                    "First/warm are invocation order; server/API cold state is not inferred. "
                    "Discovery continuation tokens remain in the receipts. Empty evidence "
                    "is never disease absence."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
