"""ASGI construction and process entry point."""

import logging

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from atlas_lyme_mcp import __version__
from atlas_lyme_mcp.application.client import AtlasClient
from atlas_lyme_mcp.config import Settings
from atlas_lyme_mcp.protection import PublicProtection
from atlas_lyme_mcp.tools.evidence import EvidenceTools
from atlas_lyme_mcp.tools.system import atlas_smoke_test, server_status


def create_server(settings: Settings | None = None, client: AtlasClient | None = None) -> MCPServer:
    """Create an MCP server without starting a listener."""
    settings = settings or Settings.from_env()
    # SDK configures INFO logging; HTTP client URLs include arguments/cursors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp.server.transport_security").setLevel(logging.ERROR)
    mcp = MCPServer(
        "atlas-lyme-mcp",
        version=__version__,
        tools=EvidenceTools(client or AtlasClient(settings.api_origin)).registered(),
    )
    mcp.tool()(server_status)
    mcp.tool()(atlas_smoke_test)

    @mcp.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp


def create_app(settings: Settings | None = None) -> Starlette:
    """Construct the Streamable HTTP ASGI app and its health route."""
    settings = settings or Settings.from_env()
    security = None
    if settings.allowed_hosts:
        security = TransportSecuritySettings(allowed_hosts=list(settings.allowed_hosts))
    app = create_server(settings).streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=security,
        max_request_body_size=16 * 1024,
    )
    app.add_middleware(PublicProtection)
    return app


def main() -> None:
    """Start one HTTP process when invoked as a command."""
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
