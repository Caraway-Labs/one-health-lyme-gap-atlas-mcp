"""Fixed public-service boundary; no domain calculation or persistence access."""

import json
import re
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from jsonschema import ValidationError

from atlas_lyme_mcp.application.public_schema import validate

REQUEST_ID: ContextVar[str] = ContextVar("atlas_http_request_id", default="unavailable")
TRACEPARENT: ContextVar[str | None] = ContextVar("atlas_traceparent", default=None)
MAX_BYTES = 256 * 1024
COLLECTIONS = {"indicators", "measures", "observations", "atlas_metadata"}
DETAILS = {"sources", "methodologies", "priority_availability", "county_detail", "state_review"}
RESEARCH_PATHS = {
    "priority_availability": "/v1/counties/{reference}/tier1-surveillance-priority/availability",
    "county_detail": "/v1/counties/{reference}",
    "state_review": "/v1/states/{reference}/review",
    "atlas_metadata": "/v1/atlas/metadata",
}
SAFE_CODES = {
    "INVALID_REQUEST",
    "RESOURCE_NOT_FOUND",
    "UNSUPPORTED_FILTER",
    "UNSUPPORTED_STRATIFICATION",
    "QUERY_TOO_BROAD",
    "RATE_LIMITED",
}


@dataclass
class RetrievalError(Exception):
    code: str
    retryable: bool = False
    retry_after_seconds: int | None = None


class AtlasClient:
    def __init__(self, origin: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # Approved origin is non-secret deployment configuration, never caller supplied.
        if origin != "https://api.onehealthatlas.org":
            raise ValueError("ATLAS_API_ORIGIN must be the approved public Atlas origin")
        self.origin = origin
        self.transport = transport
        self.calls: deque[float] = deque()
        self.active = 0

    async def get(
        self,
        resource: str,
        params: dict[str, str | int] | None,
        contract: str,
        reference: str | None = None,
    ) -> dict[str, Any]:
        # Shared across every tool: concurrency never multiplies downstream requests.
        if self.active >= 3:
            raise RetrievalError("RATE_LIMITED", True, 1)
        self.active += 1
        try:
            return await self._get(resource, params, contract, reference)
        finally:
            self.active -= 1

    async def _get(
        self,
        resource: str,
        params: dict[str, str | int] | None,
        contract: str,
        reference: str | None = None,
    ) -> dict[str, Any]:
        if resource not in COLLECTIONS | DETAILS or (
            (resource in DETAILS) != (reference is not None)
        ):
            raise RetrievalError("INVALID_REQUEST")
        if reference is not None and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", reference
        ):
            raise RetrievalError("INVALID_REQUEST")
        if resource in {"priority_availability", "county_detail"} and not re.fullmatch(
            r"[0-9]{5}", reference or ""
        ):
            raise RetrievalError("INVALID_REQUEST")
        if resource == "state_review" and not re.fullmatch(r"[A-Z]{2}", reference or ""):
            raise RetrievalError("INVALID_REQUEST")
        allowed = {
            "indicators": {"indicator_id", "page_size", "page_token"},
            "measures": {"indicator_id", "page_size", "page_token"},
            "observations": {
                "measure_id",
                "geography_type",
                "geography_id",
                "year",
                "vintage_year",
                "start_date",
                "end_date",
                "page_size",
                "page_token",
            },
            "atlas_metadata": set(),
            "priority_availability": set(),
            "county_detail": {"dataset_version"},
            "state_review": {"dataset_version"},
            "sources": set(),
            "methodologies": set(),
        }
        if set(params or {}) - allowed[resource]:
            raise RetrievalError("INVALID_REQUEST")
        now = time.monotonic()
        while self.calls and self.calls[0] <= now - 60:
            self.calls.popleft()
        # Aggregate downstream budget: API sees the MCP service as one caller.
        if len(self.calls) >= 50:
            raise RetrievalError("RATE_LIMITED", True, 60)
        self.calls.append(now)
        path = f"/v1/{resource}" + (f"/{reference}" if reference else "")
        if resource in RESEARCH_PATHS:
            path = RESEARCH_PATHS[resource].format(reference=reference)
        headers = {"Accept": "application/json", "X-Request-ID": REQUEST_ID.get()}
        if traceparent := TRACEPARENT.get():
            headers["traceparent"] = traceparent
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.origin,
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=httpx.Timeout(15, connect=2),
                ) as client,
                client.stream("GET", path, params=params, headers=headers) as response,
            ):
                if response.status_code != 200:
                    if response.status_code == 429:
                        retry = response.headers.get("Retry-After", "60")
                        raise RetrievalError(
                            "RATE_LIMITED", True, min(int(retry), 3600) if retry.isdigit() else 60
                        )
                    # Never include a backend body, HTML or private exception in errors.
                    code = "UPSTREAM_UNAVAILABLE"
                    if response.status_code == 404:
                        code = "RESOURCE_NOT_FOUND"
                    elif response.status_code == 400:
                        code = "INVALID_REQUEST"
                    raise RetrievalError(code, response.status_code >= 500)
                if response.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise RetrievalError("UPSTREAM_CONTRACT_INVALID")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise RetrievalError("RESULT_TOO_LARGE")
                    body.extend(chunk)
                value = json.loads(body)
                validate(contract, value)
                return dict(value)
        except RetrievalError:
            raise
        except (TimeoutError, httpx.HTTPError):
            raise RetrievalError("UPSTREAM_UNAVAILABLE", True) from None
        except (ValueError, TypeError, ValidationError):
            raise RetrievalError("UPSTREAM_CONTRACT_INVALID") from None
