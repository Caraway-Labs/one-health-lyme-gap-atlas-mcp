"""Opt-in bounded Pennsylvania research-task check through a real official MCP client."""

import argparse
import asyncio
import json
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable
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


class CapacityRejected(Exception):
    """Stop a task after recording its first busy response, without issuing follow-ons."""


def rate_limit_metadata(response: httpx2.Response, request_id: str) -> dict[str, Any]:
    """Retain only observed transport metadata; never inspect the response body."""
    retry = response.headers.get("Retry-After", "")
    return {
        "code": "RATE_LIMITED",
        "reason": "public_http_429",
        "retryable": True,
        "retry_after_seconds": (
            int(retry) if retry.isascii() and retry.isdigit() and len(retry) <= 4 else None
        ),
        "request_id": request_id,
        "http_status": 429,
        "transport_rejection": True,
    }


def public_rate_limit(error: Exception, request_id: str) -> dict[str, Any] | None:
    """Recognize SDK-wrapped HTTP 429 without copying exception text or response bodies."""
    pending: list[BaseException] = [error]
    for _ in range(16):
        if not pending:
            break
        item = pending.pop()
        if isinstance(item, httpx2.HTTPStatusError) and item.response.status_code == 429:
            return rate_limit_metadata(item.response, request_id)
        if isinstance(item, BaseExceptionGroup):
            pending.extend(item.exceptions[:8])
    return None


class Workflow:
    def __init__(self, client: Client, http: httpx2.AsyncClient, schemas: dict[str, Any]) -> None:
        self.client, self.http, self.schemas = client, http, schemas
        self.calls: list[dict[str, Any]] = []
        self.failures: list[str] = []
        self._request_id: str | None = None
        self._http_rejection: dict[str, Any] | None = None
        self.http.event_hooks["response"].append(self._observe_response)

    async def _observe_response(self, response: httpx2.Response) -> None:
        # The locked SDK converts plain JSON 429 into generic MCPError and drops
        # HTTP metadata. Observe headers first, restricted to this exact POST.
        request = response.request
        if (
            self._request_id is not None
            and request.headers.get("X-Request-ID") == self._request_id
            and request.method == "POST"
            and request.url.path == "/mcp"
            and response.status_code == 429
        ):
            self._http_rejection = rate_limit_metadata(response, self._request_id)

    async def call(
        self, tool: str, arguments: dict[str, Any], *, attempt: int = 1
    ) -> dict[str, Any] | None:
        request_id = str(uuid.uuid4())
        self._request_id, self._http_rejection = request_id, None
        self.http.headers["X-Request-ID"] = request_id
        started = time.monotonic()
        value: dict[str, Any] | None = None
        code = "OK"
        cancelled = False
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
        except asyncio.CancelledError:
            code = "CANCELLED"
            cancelled = True
        except Exception as error:
            # Keep arbitrary transport/publisher text out of operational summaries.
            rejection = self._http_rejection or public_rate_limit(error, request_id)
            if rejection is not None:
                value = rejection
                code = "RATE_LIMITED"
            else:
                code = type(error).__name__
        elapsed = time.monotonic() - started
        if code == "OK" and elapsed > 20:
            code = "LATE_COMPLETION"
        success = code == "OK"
        self.calls.append(
            {
                "tool": tool,
                "attempt": attempt,
                "request_id": request_id,
                "elapsed_seconds": elapsed,
                "success": success,
                "outcome": code,
                "result": value,
            }
        )
        if not success:
            self.failures.append(f"{tool}:{code}:{request_id}")
            if cancelled:
                raise asyncio.CancelledError
            if code == "RATE_LIMITED":
                raise CapacityRejected
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
        try:
            return await self._run()
        except CapacityRejected:
            return {
                "complete": False,
                "stopped_reason": "capacity_rejected",
                "failures": self.failures,
                "calls": self.calls,
                "profiles": [],
                "scores": None,
                "comparison": None,
                "priority": None,
                "resources": [],
                "evidence_references": [],
            }

    async def _run(self) -> dict[str, Any]:
        await self.discovery()
        scores = await self.call("atlas_get_atlas_scores", {"county_fips": COUNTIES})
        profiles = []
        for county in COUNTIES:
            profile = await self.call(
                "atlas_get_county_profile",
                {"county_fips": county, "selections": PROFILE_SELECTIONS},
            )
            if profile:
                if (
                    profile["county_fips"] != county
                    or [s["request"] for s in profile["selections"]] != PROFILE_SELECTIONS
                ):
                    self.failures.append("county profile identity or selection mismatch")
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
            if [row["request"] for row in comparison["matrix"]] != COMPARISON_SELECTIONS:
                self.failures.append("comparison selection mismatch")
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
                    if resource["reference_id"] != identifier or resource["meta"][
                        "release_id"
                    ] != next(iter(releases)):
                        self.failures.append("provenance identity or release mismatch")
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


async def capacity_recovery(
    workflow: Workflow,
    wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[], float] = lambda: random.uniform(0, 0.25),
) -> dict[str, Any]:
    """At most two unchanged one-indicator calls; never certify a scientific workflow."""
    name, arguments = "atlas_discover_indicators", {"page_size": 1}
    passed = False
    rejected = False
    retry_wait: float | None = None
    skipped: str | None = None
    try:
        passed = await workflow.call(name, arguments) is not None
    except CapacityRejected:
        rejected = True
        response = workflow.calls[-1]["result"] or {}
        delay = response.get("retry_after_seconds")
        if response.get("retryable") is not True:
            skipped = "not_retryable"
        elif type(delay) is not int or not 1 <= delay <= 60:
            # Do not shorten a publisher delay to fit this bounded diagnostic.
            skipped = "retry_after_outside_1_to_60_second_check"
        else:
            extra = jitter()
            if not 0 <= extra <= 0.25:
                raise ValueError("Diagnostic jitter must be between 0 and 0.25 seconds") from None
            retry_wait = delay + extra
            await wait(retry_wait)
            try:
                passed = await workflow.call(name, arguments, attempt=2) is not None
            except CapacityRejected:
                pass
    return {
        "kind": "capacity_recovery_check",
        "complete": passed,
        "recovery_exercised": len(workflow.calls) == 2,
        "recovered": rejected and passed,
        "retry_wait_seconds": retry_wait,
        "retry_skipped": skipped,
        "calls": workflow.calls,
        "failures": workflow.failures,
        "interpretation": (
            "A separate bounded transport check, not complete Pennsylvania workflow acceptance. "
            "First-attempt failures remain in the receipt; "
            "first-attempt success does not prove recovery."
        ),
    }


async def check(url: str, recovery_only: bool = False) -> dict[str, Any]:
    workflow: Workflow | None = None
    try:
        async with asyncio.timeout(125 if recovery_only else None):
            async with httpx2.AsyncClient(timeout=30) as http:
                transport = streamable_http_client(url, http_client=http)
                async with Client(transport, mode="legacy") as client:
                    schemas = {
                        tool.name: tool.output_schema for tool in (await client.list_tools()).tools
                    }
                    workflow = Workflow(client, http, schemas)
                    if recovery_only:
                        return await capacity_recovery(workflow)
                    return await workflow.run()
    except Exception as error:
        if not recovery_only:
            raise
        return {
            "kind": "capacity_recovery_check",
            "complete": False,
            "recovered": False,
            "calls": workflow.calls if workflow else [],
            "failures": [
                *(workflow.failures if workflow else []),
                "RECOVERY_CHECK_TIMEOUT"
                if isinstance(error, TimeoutError)
                else type(error).__name__,
            ],
        }


async def run(output: Path, source_sha: str, recovery_only: bool = False) -> bool:
    output.mkdir(parents=True, exist_ok=True)
    complete = True
    for i, host in enumerate(HOSTS):
        if i:
            # Respect shared instance quotas across both aliases; no background polling.
            await asyncio.sleep(60)
        try:
            result = await check(host, recovery_only)
        except Exception as error:
            result = {"complete": False, "failures": [type(error).__name__]}
        result.setdefault(
            "kind", "capacity_recovery_check" if recovery_only else "research_workflow"
        )
        result.update(
            endpoint=host,
            source_sha=source_sha,
            checked_at=datetime.now(UTC).isoformat(),
        )
        if not recovery_only:
            result["prompt"] = PROMPT
        (output / f"host-{i + 1}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        report = (
            "Capacity recovery transport check only. No scientific workflow acceptance claimed.\n\n"
            + json.dumps(result, indent=2)
            if recovery_only
            else render(result)
        )
        (output / f"host-{i + 1}.md").write_text(report, encoding="utf-8")
        complete = complete and result["complete"]
        print(
            json.dumps(
                {
                    "endpoint": host,
                    "kind": result["kind"],
                    "complete": result["complete"],
                    "recovery_exercised": result.get("recovery_exercised", False),
                    "recovered": result.get("recovered", False),
                    "attempt_count": len(result.get("calls", [])),
                    "failures": result["failures"],
                }
            ),
            flush=True,
        )
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--capacity-recovery-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        parser.error("source-sha must be an independently verified full Git commit SHA")
    if not asyncio.run(run(args.output, args.source_sha, args.capacity_recovery_only)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
