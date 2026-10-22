"""Bounded operational view over existing stdout logs; no service or paid backend."""

import argparse
import json
import math
import re
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_lyme_mcp.application.client import COLLECTIONS, DETAILS
from atlas_lyme_mcp.application.telemetry import CODES, REASONS, TOOLS


def parse_event(line: str) -> dict[str, Any] | None:
    if len(line) > 65536:
        return None
    try:
        value = json.loads(line[line.index("{") :])
        if value.get("event") != "atlas_mcp_outcome":
            return None
        stage = value["stage"]
        allowed = TOOLS if stage == "mcp_tool" else COLLECTIONS | DETAILS
        if stage not in {"mcp_tool", "upstream_api"} or value["name"] not in allowed:
            return None
        if value["outcome"] not in CODES or value["reason"] not in REASONS:
            return None
        if type(value["duration_ms"]) is not int or value["duration_ms"] < 0:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value["request_id"]):
            return None
        timestamp = datetime.fromisoformat(value["timestamp"])
        if timestamp.tzinfo is None:
            return None
        safe = {
            k: value[k]
            for k in (
                "event",
                "timestamp",
                "stage",
                "name",
                "outcome",
                "reason",
                "duration_ms",
                "request_id",
            )
        }
        if re.fullmatch(r"[0-9a-f]{32}", str(value.get("trace_id", ""))):
            safe["trace_id"] = value["trace_id"]
        status = value.get("http_status")
        if type(status) is int and 100 <= status <= 599:
            safe["http_status"] = status
        return safe
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def summarize(
    lines: Iterable[str],
    minutes: int = 15,
    request_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= minutes <= 1440:
        raise ValueError("Choose a 1–1440 minute window")
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=minutes)
    records = deque((event for line in lines if (event := parse_event(line))), maxlen=10000)
    recent = [r for r in records if cutoff <= datetime.fromisoformat(r["timestamp"]) <= now]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in recent:
        groups[row["stage"] + ":" + row["name"]].append(row)
    overview = []
    for key, values in sorted(groups.items()):
        durations = sorted(v["duration_ms"] for v in values)
        counts = Counter(v["outcome"] for v in values)
        overview.append(
            {
                "group": key,
                "calls": len(values),
                "successes": counts["OK"],
                "outcomes": dict(counts),
                "reasons": dict(Counter(v["reason"] for v in values)),
                "p50_ms": durations[(len(durations) - 1) // 2],
                "p95_ms": durations[math.ceil(len(durations) * 0.95) - 1],
            }
        )
    tools = [r for r in recent if r["stage"] == "mcp_tool"]
    failures = sum(r["outcome"] != "OK" for r in tools)
    alert = len(tools) >= 5 and failures >= 3 and failures / len(tools) >= 0.2
    result: dict[str, Any] = {
        "window_minutes": minutes,
        "events_considered": len(recent),
        "tool_calls": len(tools),
        "tool_failures": failures,
        "alert": alert,
        "groups": overview,
        "interpretation": (
            "HTTP/process health, API outcomes, tool outcomes and cited "
            "whole-workflow completion are separate checks."
        ),
    }
    if request_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", request_id):
            raise ValueError("Use a valid request ID")
        result["request_events"] = [r for r in recent if r["request_id"] == request_id][:50]
    return result


def main() -> None:
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--request-id")
    parser.add_argument("--fail-on-alert", action="store_true")
    args = parser.parse_args()
    result = summarize(sys.stdin, args.minutes, args.request_id)
    print(json.dumps(result, indent=2))
    if args.fail_on_alert and result["alert"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
