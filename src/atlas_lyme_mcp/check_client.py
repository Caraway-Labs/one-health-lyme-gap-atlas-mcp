"""Small official SDK smoke client for a running local HTTP service."""

import asyncio
import os

from mcp import Client


async def check() -> None:
    url = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
    async with Client(url) as client:
        tools = await client.list_tools()
        if "server_status" not in {tool.name for tool in tools.tools}:
            raise RuntimeError("server_status was not discovered")
        result = await client.call_tool("server_status", {})
        if result.is_error:
            raise RuntimeError("server_status returned a tool error")
        print(result)


if __name__ == "__main__":
    asyncio.run(check())
