"""Busy handling in acceptance checks is bounded and preserves failed attempts."""

import asyncio
import json
from typing import Any, cast

import httpx2
import pytest
from mcp import Client
from mcp_types import CallToolResult, TextContent

from atlas_lyme_mcp.research_workflow import Workflow, capacity_recovery


def busy(delay: Any = 1, retryable: bool = True) -> dict[str, Any]:
    return {
        "code": "RATE_LIMITED",
        "reason": "temporary_capacity",
        "retryable": retryable,
        "retry_after_seconds": delay,
    }


class SequenceClient:
    def __init__(self, values: list[dict[str, Any]]) -> None:
        self.values = iter(values)
        self.arguments: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        self.arguments.append((name, dict(arguments)))
        value = next(self.values)
        return CallToolResult(
            is_error="code" in value,
            structured_content=value,
            content=[TextContent(type="text", text=json.dumps(value))],
        )


@pytest.mark.parametrize("prior_success", [False, True])
def test_full_workflow_stops_after_first_capacity_rejection(prior_success: bool) -> None:
    async def check() -> None:
        values: list[dict[str, Any]] = (
            [{"meta": {"next_page_token": None, "measure_page_tokens": {}}}]
            if prior_success
            else []
        )
        client = SequenceClient([*values, busy()])
        async with httpx2.AsyncClient() as http:
            workflow = Workflow(
                cast(Client, client), http, {"atlas_discover_indicators": {"type": "object"}}
            )
            result = await workflow.run()
        assert not result["complete"] and result["stopped_reason"] == "capacity_rejected"
        assert len(client.arguments) == len(result["calls"]) == (2 if prior_success else 1)
        assert result["calls"][-1]["attempt"] == 1
        assert result["calls"][-1]["result"] == busy()
        assert result["failures"] and result["scores"] is None

    asyncio.run(check())


@pytest.mark.parametrize("second, recovered", [({"meta": {}}, True), (busy(), False)])
def test_one_retry_waits_full_delay_and_retains_both_attempts(
    second: dict[str, Any], recovered: bool
) -> None:
    async def check() -> None:
        client = SequenceClient([busy(60), second])
        waits = []

        async def wait(seconds: float) -> None:
            assert len(client.arguments) == 1
            waits.append(seconds)

        async with httpx2.AsyncClient() as http:
            workflow = Workflow(
                cast(Client, client), http, {"atlas_discover_indicators": {"type": "object"}}
            )
            result = await capacity_recovery(workflow, wait=wait, jitter=lambda: 0.125)
        assert waits == [60.125]
        assert client.arguments == [("atlas_discover_indicators", {"page_size": 1})] * 2
        assert result["kind"] == "capacity_recovery_check"
        assert result["complete"] is recovered and result["recovered"] is recovered
        assert result["recovery_exercised"] is True
        assert [call["attempt"] for call in result["calls"]] == [1, 2]
        assert len({call["request_id"] for call in result["calls"]}) == 2
        assert result["calls"][0]["outcome"] == "RATE_LIMITED"
        assert result["failures"][0].startswith("atlas_discover_indicators:RATE_LIMITED:")

    asyncio.run(check())


@pytest.mark.parametrize(
    "response",
    [
        busy(61),
        busy(None),
        busy("1"),
        busy(True),
        busy(0),
        busy(1, False),
        {"code": "RESOURCE_NOT_FOUND"},
        {"meta": {}},
    ],
)
def test_nonretryable_or_unbounded_wait_never_causes_a_second_call(
    response: dict[str, Any],
) -> None:
    async def check() -> None:
        client = SequenceClient([response])

        async def no_wait(seconds: float) -> None:
            raise AssertionError("No wait or repeat should occur")

        async with httpx2.AsyncClient() as http:
            workflow = Workflow(
                cast(Client, client), http, {"atlas_discover_indicators": {"type": "object"}}
            )
            result = await capacity_recovery(workflow, wait=no_wait)
        assert len(client.arguments) == 1
        assert result["recovery_exercised"] is False and result["recovered"] is False
        assert result["calls"][0]["result"] == response

    asyncio.run(check())


def test_cancelled_attempt_is_recorded_without_follow_on_requests() -> None:
    async def check() -> None:
        entered = asyncio.Event()

        class WaitingClient:
            async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
                entered.set()
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

        async with httpx2.AsyncClient() as http:
            workflow = Workflow(cast(Client, WaitingClient()), http, {})
            task = asyncio.create_task(workflow.call("atlas_discover_indicators", {"page_size": 1}))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(workflow.calls) == 1
        assert workflow.calls[0]["outcome"] == "CANCELLED"
        assert workflow.calls[0]["attempt"] == 1

    asyncio.run(check())


@pytest.mark.parametrize("wrapped", [False, True])
def test_http_429_stops_workflow_without_copying_private_response_text(wrapped: bool) -> None:
    async def check() -> None:
        class RejectedClient:
            calls = 0

            async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
                self.calls += 1
                request = httpx2.Request("POST", "https://mcp.onehealthatlas.org/mcp")
                response = httpx2.Response(
                    429,
                    request=request,
                    headers={"Retry-After": "60"},
                    text="private rejection body",
                )
                error = httpx2.HTTPStatusError(
                    "private exception", request=request, response=response
                )
                if wrapped:
                    raise ExceptionGroup("private group", [error])
                raise error

        client = RejectedClient()
        async with httpx2.AsyncClient() as http:
            workflow = Workflow(cast(Client, client), http, {})
            result = await workflow.run()
        assert client.calls == 1 and result["stopped_reason"] == "capacity_rejected"
        assert result["calls"][0]["outcome"] == "RATE_LIMITED"
        assert result["calls"][0]["result"]["http_status"] == 429
        assert result["calls"][0]["result"]["retry_after_seconds"] == 60
        assert "private" not in json.dumps(result)

    asyncio.run(check())


def test_noncapacity_contract_failure_retains_the_original_result_without_retry() -> None:
    async def check() -> None:
        value = {"fixture": "original public payload"}
        client = SequenceClient([value])
        async with httpx2.AsyncClient() as http:
            workflow = Workflow(
                cast(Client, client),
                http,
                {"atlas_discover_indicators": {"type": "object", "required": ["missing"]}},
            )
            result = await capacity_recovery(workflow)
        assert len(client.arguments) == 1 and not result["complete"]
        assert result["calls"][0]["outcome"] == "ValidationError"
        assert result["calls"][0]["result"] == value

    asyncio.run(check())
