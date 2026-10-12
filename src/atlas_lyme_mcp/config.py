"""Non-secret runtime configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8000
    allowed_hosts: tuple[str, ...] = ()
    api_origin: str = "https://api.onehealthatlas.org"

    @classmethod
    def from_env(cls) -> "Settings":
        port = int(os.getenv("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        hosts = tuple(
            host.strip() for host in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if host.strip()
        )
        origin = os.getenv("ATLAS_API_ORIGIN", "https://api.onehealthatlas.org")
        if origin != "https://api.onehealthatlas.org":
            raise ValueError("ATLAS_API_ORIGIN must be the approved public Atlas origin")
        return cls(
            host=os.getenv("HOST", "0.0.0.0"), port=port, allowed_hosts=hosts, api_origin=origin
        )
