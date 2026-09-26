"""Official SDK protocol check for a running local or remote HTTP service."""

import asyncio
import os

from mcp import Client

from atlas_lyme_mcp import __version__
from atlas_lyme_mcp.tools.system import SMOKE_MESSAGE


async def check() -> None:
    url = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
    async with Client(url, mode="legacy") as client:
        if not client.protocol_version:
            raise RuntimeError("MCP initialization did not negotiate a protocol version")
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        expected_names = {"server_status", "atlas_smoke_test"}
        if names != expected_names:
            raise RuntimeError(f"Unexpected tool list: {sorted(names)}")

        status = await client.call_tool("server_status", {})
        if status.is_error or status.structured_content != {
            "service": "atlas-lyme-mcp",
            "version": __version__,
            "status": "ok",
        }:
            raise RuntimeError(f"Unexpected server_status result: {status}")

        smoke = await client.call_tool("atlas_smoke_test", {})
        expected_smoke = {
            "service": "atlas-lyme-mcp",
            "version": __version__,
            "status": "ok",
            "message": SMOKE_MESSAGE,
        }
        if smoke.is_error or smoke.structured_content != expected_smoke:
            raise RuntimeError(f"Unexpected atlas_smoke_test result: {smoke}")
        print(f"MCP initialized: {client.protocol_version}")
        print(f"Tools: {', '.join(sorted(names))}")
        print(f"server_status: {status.structured_content}")
        print(f"atlas_smoke_test: {smoke.structured_content}")


if __name__ == "__main__":
    asyncio.run(check())
