"""Ordered bounded I/O, with fail-fast cancellation and no background work."""

import asyncio
from collections.abc import Awaitable, Sequence
from typing import Any, cast


async def bounded(operations: Sequence[Awaitable[dict[str, Any]]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any] | None] = [None] * len(operations)
    next_index = 0

    async def worker() -> None:
        nonlocal next_index
        while next_index < len(operations):
            index = next_index
            next_index += 1
            results[index] = await operations[index]

    workers = [asyncio.create_task(worker()) for _ in range(min(3, len(operations)))]
    try:
        await asyncio.gather(*workers)
        return cast(list[dict[str, Any]], results)
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        for operation in operations[next_index:]:
            if hasattr(operation, "close"):
                operation.close()
