"""Server behavior without any external Atlas dependency."""

import importlib
from unittest.mock import patch

from starlette.testclient import TestClient

from atlas_lyme_mcp.config import Settings
from atlas_lyme_mcp.server import create_app, create_server
from atlas_lyme_mcp.tools.system import SMOKE_MESSAGE, atlas_smoke_test, server_status


def test_config_defaults(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    for key in ("HOST", "PORT", "MCP_ALLOWED_HOSTS"):
        monkeypatch.delenv(key, raising=False)
    assert Settings.from_env() == Settings()


def test_config_overrides(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "example.org, example.org:*")
    assert Settings.from_env() == Settings("127.0.0.1", 9123, ("example.org", "example.org:*"))


def test_application_and_health() -> None:
    assert create_server(Settings()) is not None
    with TestClient(create_app(Settings())) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_operational_capability() -> None:
    assert server_status() == {"service": "atlas-lyme-mcp", "version": "0.1.0", "status": "ok"}
    assert atlas_smoke_test() == {
        "service": "atlas-lyme-mcp",
        "version": "0.1.0",
        "status": "ok",
        "message": SMOKE_MESSAGE,
    }
    assert SMOKE_MESSAGE == (
        "Atlas MCP is alive on DigitalOcean. The ticks have been notified and are "
        "pretending this was all part of the plan."
    )


def test_unlisted_host_is_rejected_by_mcp() -> None:
    settings = Settings(allowed_hosts=("mcp.example.org", "mcp.example.org:*"))
    with TestClient(create_app(settings), base_url="https://mcp.example.org") as client:
        allowed = client.post("/mcp", json={})
        rejected = client.post("/mcp", json={}, headers={"Host": "other.example.org"})
    assert allowed.status_code != 421
    assert rejected.status_code == 421


def test_import_has_no_process_side_effect() -> None:
    with patch("uvicorn.run") as run:
        import atlas_lyme_mcp.server as module

        importlib.reload(module)
    run.assert_not_called()
