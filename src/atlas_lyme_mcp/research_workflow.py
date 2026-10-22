"""Opt-in bounded Pennsylvania research-task check through a real official MCP client."""

import argparse
import asyncio
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

HOSTS = (
    "https://mcp.onehealthatlas.org/mcp",
    "https://oh-lyme-mcp-dev-7jcfi.ondigitalocean.app/mcp",
)
COUNTIES = ["42029", "42091"]
PROMPT = (
    "Act as a public-health epidemiologist deciding where to focus limited Lyme disease "
    "surveillance resources in Pennsylvania. Use One Health Atlas to investigate Chester "
    "and Montgomery counties. Compare their surveillance evidence, identify any meaningful "
    "discrepancies or blind spots, and give me a brief, evidence-backed recommendation for "
    "what to investigate next."
)
PROFILE_SELECTIONS: list[dict[str, Any]] = [
    {"measure_id": m, "start_date": "2025-12-31", "end_date": "2025-12-31"}
    for m in ("scapularis_status", "burgdorferi_status")
] + [{"measure_id": "population_2022", "vintage_year": 2022}]
COMPARISON_SELECTIONS: list[dict[str, Any]] = [
    {"measure_id": m, "start_date": "2025-01-01", "end_date": "2025-01-31"}
    for m in ("nclimgrid_tavg_county_day", "nclimgrid_prcp_county_day")
] + [{"measure_id": "nlcd_forest_area_share_county_year", "year": 2025}]


class Workflow:
    def __init__(self, client: Client, http: httpx2.AsyncClient, schemas: dict[str, Any]) -> None:
        self.client, self.http, self.schemas = client, http, schemas
        self.calls: list[dict[str, Any]] = []
        self.failures: list[str] = []

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        request_id = str(uuid.uuid4())
        self.http.headers["X-Request-ID"] = request_id
        started = time.monotonic()
        value: dict[str, Any] | None = None
        code = "OK"
        try:
            result = await self.client.call_tool(tool, arguments)
            value = result.structured_content
            if result.is_error or value is None:
                code = str((value or {}).get("code", "SDK_OR_TOOL_ERROR"))
            else:
                Draft202012Validator(self.schemas[tool]).validate(value)
                if (
                    not result.content
                    or result.content[0].type != "text"
                    or json.loads(result.content[0].text) != value
                ):
                    code = "CONTENT_PARITY_INVALID"
        except Exception as error:
            # Keep arbitrary transport/publisher text out of operational summaries.
            code = type(error).__name__
        elapsed = time.monotonic() - started
        if code == "OK" and elapsed > 20:
            code = "LATE_COMPLETION"
        success = code == "OK"
        self.calls.append(
            {
                "tool": tool,
                "request_id": request_id,
                "elapsed_seconds": elapsed,
                "success": success,
                "outcome": code,
                "result": value,
            }
        )
        if not success:
            self.failures.append(f"{tool}:{code}:{request_id}")
            return None
        return value

    async def discovery(self) -> None:
        token: str | None = None
        measure_tokens: dict[str, str] = {}
        for _ in range(3):
            args: dict[str, Any] = {"page_size": 5}
            if token:
                args["page_token"] = token
            page = await self.call("atlas_discover_indicators", args)
            if page is None:
                return
            measure_tokens.update(page["meta"]["measure_page_tokens"])
            token = page["meta"]["next_page_token"]
            if token is None:
                break
        if token is not None:
            self.failures.append("indicator pagination bound reached; catalog incomplete")
        continued = 0
        for indicator, cursor in measure_tokens.items():
            while cursor and continued < 3:
                page = await self.call(
                    "atlas_discover_indicators",
                    {"indicator_id": indicator, "measure_page_token": cursor, "page_size": 5},
                )
                continued += 1
                if page is None:
                    return
                cursor = page["meta"]["measure_page_tokens"].get(indicator)
            if cursor:
                self.failures.append("measure pagination bound reached; catalog incomplete")

    async def run(self) -> dict[str, Any]:
        await self.discovery()
        scores = await self.call("atlas_get_atlas_scores", {"county_fips": COUNTIES})
        profiles = []
        for county in COUNTIES:
            profile = await self.call(
                "atlas_get_county_profile",
                {"county_fips": county, "selections": PROFILE_SELECTIONS},
            )
            if profile:
                if len(profile["selections"]) != 3 or any(
                    s["next_page_token"] is not None for s in profile["selections"]
                ):
                    self.failures.append("county profile incomplete")
                profiles.append(profile)
        comparison = await self.call(
            "atlas_compare_counties", {"county_fips": COUNTIES, "selections": COMPARISON_SELECTIONS}
        )
        priority = await self.call("atlas_get_surveillance_priority", {"county_fips": COUNTIES})
        observations = [o for p in profiles for s in p["selections"] for o in s["observations"]]
        if comparison:
            if (
                comparison.get("complete") is not True
                or len(comparison["matrix"]) != 3
                or any(
                    [c["county_fips"] for c in row["counties"]] != COUNTIES
                    or any(c["next_page_token"] is not None for c in row["counties"])
                    for row in comparison["matrix"]
                )
            ):
                self.failures.append("comparison incomplete")
            observations.extend(
                o
                for row in comparison["matrix"]
                for c in row["counties"]
                for o in c["observations"]
            )
        releases = {o["release_id"] for o in observations}
        if scores:
            releases.add(scores["metadata"]["release_id"])
            if [c["fips"] for c in scores["counties"]] != COUNTIES:
                self.failures.append("score county mismatch")
        if comparison:
            releases.add(comparison["release_id"])
        if len(releases) != 1 or None in releases:
            self.failures.append("unknown or mixed research evidence release")
        references = sorted(
            {
                (kind, o[key])
                for o in observations
                for kind, key in (("source", "source_id"), ("methodology", "methodology_id"))
                if o[key] is not None
            }
        )
        resources = []
        if len(references) > 8:
            self.failures.append("provenance bound reached; cited workflow incomplete")
        if len(releases) == 1 and None not in releases:
            for kind, identifier in references[:8]:
                resource = await self.call(
                    "atlas_get_evidence_provenance",
                    {
                        "reference_type": kind,
                        "reference_id": identifier,
                        "expected_release_id": next(iter(releases)),
                    },
                )
                if resource:
                    resources.append(resource)
        return {
            "complete": not self.failures,
            "failures": self.failures,
            "calls": self.calls,
            "profiles": profiles,
            "scores": scores,
            "comparison": comparison,
            "priority": priority,
            "resources": resources,
            "evidence_references": [o["evidence"] for o in observations],
        }


def render(result: dict[str, Any]) -> str:
    if not result["complete"]:
        return (
            "Pennsylvania workflow incomplete.\n\n"
            + "\n".join(result["failures"])
            + "\n\nFailed retrieval is not zero disease evidence or biological absence. "
            "No complete allocation recommendation is claimed. See the structured receipt.\n"
        )
    scores = result["scores"]
    lines = [
        "# Chester and Montgomery surveillance evidence",
        "",
        f"Prompt: {PROMPT}",
        "",
        f"Published evidence release: {scores['metadata']['release_id']}.",
        "",
        "## Published county comparison",
        "",
        "| County | 2023 published case floor | Published Atlas score | Publisher priority label |",
        "|---|---:|---:|---|",
    ]
    for county in scores["counties"]:
        lines.append(
            f"| {county['county']} ({county['fips']}) | {county['case_count_floor_2023']} | "
            f"{county['score']['score']} | {county['priority']} |"
        )
    lines.extend(
        [
            "",
            "These are published surveillance floors and follow-up scores, not complete "
            "incidence, diagnosis or disease-risk predictions. [Publisher sources below]",
            "",
        ]
    )
    for profile in result["profiles"]:
        lines.append(f"County {profile['county_fips']}:")
        for selection in profile["selections"]:
            for row in selection["observations"]:
                lines.append(
                    f"- {row['measure_id']}: {row['value']} ({row['value_state']}); "
                    f"original period {row['period_start']} to {row['period_end']}; "
                    f"source {row['source_id']}; evidence {row['evidence']['resource_id']}."
                )
            if not selection["observations"]:
                lines.append(
                    f"- {selection['request']['measure_id']}: empty selection; "
                    "see original availability metadata, not zero."
                )
    lines.extend(["", "## Climate, forest and model limitations", ""])
    for row in result["comparison"]["matrix"]:
        for county in row["counties"]:
            lines.append(
                f"- {row['request']['measure_id']}, {county['county_fips']}: "
                f"{len(county['observations'])} published records; comparability "
                f"{row['comparability']}; availability "
                f"{json.dumps(county['availability'], ensure_ascii=False)}"
            )
    lines.extend(
        [
            "",
            "Published model review-priority results (kept distinct from Atlas scores):",
            "",
            json.dumps(result["priority"], ensure_ascii=False),
            "",
            "## What to investigate next",
            "",
            "Audit county-specific reporting completeness and original source coverage before "
            "allocating resources. Compare the published human floors with cumulative "
            "tick/pathogen evidence using their original periods and population vintage. "
            "Investigate explicit unavailable forest evidence before environmental comparisons. "
            "A lower floor, No records, an empty selection or failed retrieval does not "
            "establish lower disease burden or biological absence. Model review priority "
            "is a follow-up cue, not a disease-risk ranking.",
            "",
            "## Publisher sources and retained limitations",
            "",
        ]
    )
    for source in scores["metadata"]["sources"]:
        lines.append(
            f"- {source['label']}: {source['url']} (vintage {source['vintage']}). {source['note']}"
        )
    lines.append(scores["metadata"]["limitations"])
    for resource in result["resources"]:
        lines.append(
            f"- Resolved {resource['reference_type']} {resource['reference_id']}: "
            f"{json.dumps(resource['resource'], ensure_ascii=False)}"
        )
    lines.append(
        "\nThe structured receipt retains every original observation, evidence reference "
        "and limitation; response time is not source freshness."
    )
    return "\n".join(lines) + "\n"


async def check(url: str) -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=30) as http:
        transport = streamable_http_client(url, http_client=http)
        async with Client(transport, mode="legacy") as client:
            schemas = {tool.name: tool.output_schema for tool in (await client.list_tools()).tools}
            return await Workflow(client, http, schemas).run()


async def run(output: Path, source_sha: str) -> bool:
    output.mkdir(parents=True, exist_ok=True)
    complete = True
    for i, host in enumerate(HOSTS):
        if i:
            # Respect shared instance quotas across both aliases; no background polling.
            await asyncio.sleep(60)
        try:
            result = await check(host)
        except Exception as error:
            result = {"complete": False, "failures": [type(error).__name__]}
        result.update(
            endpoint=host,
            source_sha=source_sha,
            checked_at=datetime.now(UTC).isoformat(),
            prompt=PROMPT,
        )
        (output / f"host-{i + 1}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (output / f"host-{i + 1}.md").write_text(render(result), encoding="utf-8")
        complete = complete and result["complete"]
        print(
            json.dumps(
                {"endpoint": host, "complete": result["complete"], "failures": result["failures"]}
            ),
            flush=True,
        )
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        parser.error("source-sha must be an independently verified full Git commit SHA")
    if not asyncio.run(run(args.output, args.source_sha)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
