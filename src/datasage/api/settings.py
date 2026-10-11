"""Configuration for the HTTP service, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

AccessMode = Literal["api-key", "dev", "public-demo"]


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {raw!r}")


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class ApiSettings:
    """Service settings.

    Access modes:

    * keys configured (``DATASAGE_API_KEYS``) -> every ``/api`` call needs ``X-API-Key`` or a
      Bearer token; the configured LLM provider is used and raw SQL is allowed.
    * ``dev_mode`` -> no auth and full access; meant for ``localhost`` only.
    * neither -> public demo: anonymous callers get the offline mock provider only, each with
      their own private workspace (sample data + their uploads).
    """

    api_keys: tuple[str, ...] = ()
    dev_mode: bool = False
    cors_origins: tuple[str, ...] = ()
    rate_limit_per_minute: int = 120
    ask_limit_per_minute: int = 30
    upload_limit_per_minute: int = 10
    trust_proxy: bool = False
    max_rows: int = 500
    query_timeout_ms: int = 2000
    max_workspaces: int = 200
    max_uploads_per_workspace: int = 5

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def access_mode(self) -> AccessMode:
        if self.auth_enabled:
            return "api-key"
        return "dev" if self.dev_mode else "public-demo"

    @property
    def public_demo(self) -> bool:
        return self.access_mode == "public-demo"

    @classmethod
    def from_env(cls) -> ApiSettings:
        return cls(
            api_keys=_env_list("DATASAGE_API_KEYS"),
            dev_mode=env_bool("DATASAGE_DEV_MODE", False),
            cors_origins=_env_list("DATASAGE_CORS_ORIGINS"),
            rate_limit_per_minute=env_int("DATASAGE_RATE_LIMIT_PER_MINUTE", 120),
            ask_limit_per_minute=env_int("DATASAGE_ASK_LIMIT_PER_MINUTE", 30),
            upload_limit_per_minute=env_int("DATASAGE_UPLOAD_LIMIT_PER_MINUTE", 10),
            trust_proxy=env_bool("DATASAGE_TRUST_PROXY", False),
            max_rows=env_int("DATASAGE_MAX_ROWS", 500),
            query_timeout_ms=env_int("DATASAGE_QUERY_TIMEOUT_MS", 2000),
            max_workspaces=env_int("DATASAGE_MAX_WORKSPACES", 200),
            max_uploads_per_workspace=env_int("DATASAGE_MAX_UPLOADS", 5),
        )
