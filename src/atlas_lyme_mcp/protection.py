"""Single-instance anonymous request budgets and existing Atlas correlation conventions."""

import hashlib
import re
import secrets
import time
import uuid
from collections import deque

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from atlas_lyme_mcp.application.client import REQUEST_ID, TRACEPARENT
from atlas_lyme_mcp.application.mcp_tracing import ingress_rejection_span
from atlas_lyme_mcp.application.telemetry import record


class PublicProtection:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.salt = secrets.token_bytes(32)
        self.requests: dict[bytes, deque[float]] = {}
        self.global_requests: deque[float] = deque()
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/mcp":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        supplied = headers.get("x-request-id", "")
        request_id = (
            supplied if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", supplied) else str(uuid.uuid4())
        )
        trace = headers.get("traceparent", "")
        valid_trace = bool(re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", trace))
        if valid_trace and (trace.split("-")[1] == "0" * 32 or trace.split("-")[2] == "0" * 16):
            valid_trace = False
        tokens = REQUEST_ID.set(request_id), TRACEPARENT.set(trace if valid_trace else None)
        try:
            now = time.monotonic()
            # Ignore spoofable forwarding headers; aggregate/global ceilings remain enforced.
            client = scope.get("client") or ("unknown", 0)
            key = hashlib.sha256(self.salt + client[0].encode()).digest()
            for stale in [k for k, q in self.requests.items() if not q or q[-1] <= now - 60]:
                del self.requests[stale]
            queue = (
                self.requests.setdefault(key, deque())
                if len(self.requests) < 1024 or key in self.requests
                else None
            )
            for q in (queue, self.global_requests):
                if q is not None:
                    while q and q[0] <= now - 60:
                        q.popleft()
            if self.active >= 8:
                ingress_cause = "active_mcp_requests"
            elif queue is None:
                ingress_cause = "client_table_full"
            elif len(queue) >= 30:
                ingress_cause = "per_client_rate"
            elif len(self.global_requests) >= 60:
                ingress_cause = "global_rate"
            else:
                ingress_cause = None
            if ingress_cause is not None:
                reason = (
                    "request_budget"
                    if ingress_cause != "active_mcp_requests"
                    else "temporary_capacity"
                )
                with ingress_rejection_span(ingress_cause):
                    record("public_ingress", "mcp", "RATE_LIMITED", reason, 0, 429)
                response = JSONResponse(
                    {
                        "code": "RATE_LIMITED",
                        "request_id": request_id,
                        "retryable": True,
                        "retry_after_seconds": 60,
                        "reason": reason,
                        "message": (
                            "Wait for Retry-After, then retry once with jitter; "
                            "avoid parallel retries."
                        ),
                    },
                    status_code=429,
                    headers={"Retry-After": "60", "Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            assert queue is not None  # The budget rejection above includes a missing client queue.
            queue.append(now)
            self.global_requests.append(now)
            self.active += 1
            try:
                await self.app(scope, receive, send)
            finally:
                self.active -= 1
        finally:
            REQUEST_ID.reset(tokens[0])
            TRACEPARENT.reset(tokens[1])
