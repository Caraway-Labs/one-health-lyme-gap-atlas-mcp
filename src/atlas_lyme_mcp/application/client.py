"""Fixed public-service boundary; no domain calculation or persistence access."""

import asyncio
import json
import re
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from jsonschema import ValidationError

from atlas_lyme_mcp.application.public_schema import validate
from atlas_lyme_mcp.application.telemetry import record

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
    reason: str | None = None


class AtlasClient:
    def __init__(self, origin: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # Approved origin is non-secret deployment configuration, never caller supplied.
        if origin != "https://api.onehealthatlas.org":
            raise ValueError("ATLAS_API_ORIGIN must be the approved public Atlas origin")
        self.origin = origin
        self.transport = transport
        self.calls: deque[float] = deque()
        self.active = 0
        self.waiting = 0
        self._capacity = asyncio.Semaphore(3)
        self._session: httpx.AsyncClient | None = None

    def _new_session(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.origin,
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(15, connect=2),
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=3),
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Reuse approved-origin connections only within the application's event loop."""
        if self._session is not None:
            raise RuntimeError("Atlas HTTP lifespan already running")
        async with self._new_session() as session:
            self._session = session
            try:
                yield
            finally:
                self._session = None

    @asynccontextmanager
    async def _http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._session is not None:
            yield self._session
        else:
            # Importable direct adapters/tests retain request-owned cleanup.
            async with self._new_session() as session:
                yield session

    async def get(
        self,
        resource: str,
        params: dict[str, str | int] | None,
        contract: str,
        reference: str | None = None,
    ) -> dict[str, Any]:
        # Shared across every tool: concurrency never multiplies downstream requests.
        queued = self._capacity.locked()
        if queued and self.waiting >= 3:
            raise RetrievalError("RATE_LIMITED", True, 1, "temporary_capacity")
        if queued:
            self.waiting += 1
        try:
            # Scheduling consumes the existing whole-tool deadline, never extends it.
            async with asyncio.timeout(1):
                await self._capacity.acquire()
        except TimeoutError:
            raise RetrievalError("RATE_LIMITED", True, 1, "temporary_capacity") from None
        finally:
            if queued:
                self.waiting -= 1
        self.active += 1
        try:
            return await self._get(resource, params, contract, reference)
        finally:
            self.active -= 1
            self._capacity.release()

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
            raise RetrievalError("RATE_LIMITED", True, 60, "request_budget")
        self.calls.append(now)
        path = f"/v1/{resource}" + (f"/{reference}" if reference else "")
        if resource in RESEARCH_PATHS:
            path = RESEARCH_PATHS[resource].format(reference=reference)
        headers = {"Accept": "application/json", "X-Request-ID": REQUEST_ID.get()}
        if traceparent := TRACEPARENT.get():
            headers["traceparent"] = traceparent
        started = time.monotonic()
        outcome, reason = "OK", "completed"
        status: int | None = None
        try:
            async with (
                self._http_client() as client,
                client.stream("GET", path, params=params, headers=headers) as response,
            ):
                status = response.status_code
                if response.status_code != 200:
                    if response.status_code == 429:
                        retry = response.headers.get("Retry-After", "60")
                        raise RetrievalError(
                            "RATE_LIMITED",
                            True,
                            max(1, min(int(retry), 3600)) if retry.isdigit() else 60,
                            "publisher_rate_limit",
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
        except asyncio.CancelledError:
            outcome, reason = "CANCELLED", "cancelled"
            raise
        except RetrievalError as error:
            outcome = error.code
            reason = error.reason or {
                "UPSTREAM_CONTRACT_INVALID": "contract_invalid",
                "INVALID_REQUEST": "invalid_input",
            }.get(error.code, "retrieval_failed")
            error.reason = reason
            raise
        except (TimeoutError, httpx.TimeoutException):
            outcome, reason = "UPSTREAM_UNAVAILABLE", "upstream_timeout"
            raise RetrievalError(outcome, True, reason=reason) from None
        except httpx.HTTPError:
            outcome, reason = "UPSTREAM_UNAVAILABLE", "upstream_transport"
            raise RetrievalError(outcome, True, reason=reason) from None
        except (ValueError, TypeError, ValidationError):
            outcome, reason = "UPSTREAM_CONTRACT_INVALID", "contract_invalid"
            raise RetrievalError(outcome, reason=reason) from None
        except Exception:
            outcome, reason = "UNEXPECTED_ERROR", "unexpected_error"
            raise
        finally:
            record(
                "upstream_api",
                resource,
                outcome,
                reason,
                int((time.monotonic() - started) * 1000),
                status,
            )
