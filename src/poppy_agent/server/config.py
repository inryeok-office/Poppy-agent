"""Environment-backed Poppy-Server client configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse


class ServerConfigurationError(ValueError):
    """Raised when server configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Validated settings for registration and heartbeat transport."""

    server_url: str
    agent_token: str = field(repr=False)
    agent_name: str
    agent_version: str
    sdk_version: str
    platform: str
    heartbeat_interval_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    max_retries: int = 1

    def __post_init__(self) -> None:
        normalized_url = self.server_url.rstrip("/")
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ServerConfigurationError("POPPY_SERVER_URL must be an HTTP(S) URL")
        if not self.agent_token.strip():
            raise ServerConfigurationError("POPPY_AGENT_TOKEN is required")
        for name, value in (
            ("POPPY_AGENT_NAME", self.agent_name),
            ("POPPY_AGENT_VERSION", self.agent_version),
            ("POPPY_SDK_VERSION", self.sdk_version),
            ("POPPY_AGENT_PLATFORM", self.platform),
        ):
            if not value.strip():
                raise ServerConfigurationError(f"{name} is required")
        if self.heartbeat_interval_seconds <= 0:
            raise ServerConfigurationError("heartbeat interval must be positive")
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ServerConfigurationError("server timeouts must be positive")
        if self.max_retries < 0:
            raise ServerConfigurationError("max retries must not be negative")
        object.__setattr__(self, "server_url", normalized_url)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> ServerConfig:
        """Load server settings without printing or exposing the token."""
        values = os.environ if environ is None else environ
        return cls(
            server_url=values.get("POPPY_SERVER_URL", "").strip(),
            agent_token=values.get("POPPY_AGENT_TOKEN", ""),
            agent_name=values.get("POPPY_AGENT_NAME", "").strip(),
            agent_version=values.get("POPPY_AGENT_VERSION", "").strip(),
            sdk_version=values.get("POPPY_SDK_VERSION", "").strip(),
            platform=values.get("POPPY_AGENT_PLATFORM", "").strip(),
            heartbeat_interval_seconds=_float_value(
                values, "POPPY_HEARTBEAT_INTERVAL_SECONDS", 30.0
            ),
            connect_timeout_seconds=_float_value(
                values, "POPPY_SERVER_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            read_timeout_seconds=_float_value(values, "POPPY_SERVER_READ_TIMEOUT_SECONDS", 10.0),
            max_retries=_int_value(values, "POPPY_SERVER_MAX_RETRIES", 1),
        )


def _float_value(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ServerConfigurationError(f"{name} must be a number") from exc


def _int_value(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ServerConfigurationError(f"{name} must be an integer") from exc
