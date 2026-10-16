"""Environment-backed configuration for the Agent core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite


class ConfigurationError(ValueError):
    """Raised when required Agent configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Validated configuration needed to construct the Phase 2 Agent."""

    robot_mode: str
    robot_id: str
    enable_physical_execution: bool = False
    network_interface: str | None = None
    robot_model: str | None = None
    robot_edition: str | None = None
    robot_firmware_version: str | None = None
    unitree_sdk_version: str | None = None
    unitree_telemetry_stale_timeout_seconds: float | None = None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> AgentConfig:
        """Load and validate configuration from an environment mapping."""
        values = os.environ if environ is None else environ
        robot_mode = values.get("ROBOT_MODE", "").strip().lower()
        robot_id = values.get("POPPY_ROBOT_ID", "").strip()
        raw_physical_execution = values.get("POPPY_ENABLE_PHYSICAL_EXECUTION", "false")
        physical_execution_enabled = _parse_bool(
            raw_physical_execution,
            "POPPY_ENABLE_PHYSICAL_EXECUTION",
        )

        if not robot_mode:
            raise ConfigurationError("ROBOT_MODE is required")
        if not robot_id:
            raise ConfigurationError("POPPY_ROBOT_ID is required")
        if robot_mode not in {"mock", "unitree"}:
            raise ConfigurationError("ROBOT_MODE must be mock or unitree")

        unitree_values = {
            "UNITREE_NETWORK_INTERFACE": values.get("UNITREE_NETWORK_INTERFACE", "").strip(),
            "POPPY_ROBOT_MODEL": values.get("POPPY_ROBOT_MODEL", "").strip(),
            "POPPY_ROBOT_EDITION": values.get("POPPY_ROBOT_EDITION", "").strip(),
            "POPPY_ROBOT_FIRMWARE_VERSION": values.get("POPPY_ROBOT_FIRMWARE_VERSION", "").strip(),
            "UNITREE_SDK_VERSION": values.get("UNITREE_SDK_VERSION", "").strip(),
            "POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS": values.get(
                "POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS", ""
            ).strip(),
        }
        if robot_mode == "unitree":
            for name, value in unitree_values.items():
                if not value:
                    raise ConfigurationError(f"{name} is required for ROBOT_MODE=unitree")

        telemetry_stale_timeout_seconds: float | None = None
        if unitree_values["POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS"]:
            telemetry_stale_timeout_seconds = _parse_positive_finite_float(
                unitree_values["POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS"],
                "POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS",
            )

        return cls(
            robot_mode=robot_mode,
            robot_id=robot_id,
            enable_physical_execution=physical_execution_enabled,
            network_interface=unitree_values["UNITREE_NETWORK_INTERFACE"] or None,
            robot_model=unitree_values["POPPY_ROBOT_MODEL"] or None,
            robot_edition=unitree_values["POPPY_ROBOT_EDITION"] or None,
            robot_firmware_version=unitree_values["POPPY_ROBOT_FIRMWARE_VERSION"] or None,
            unitree_sdk_version=unitree_values["UNITREE_SDK_VERSION"] or None,
            unitree_telemetry_stale_timeout_seconds=telemetry_stale_timeout_seconds,
        )


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _parse_positive_finite_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive finite number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ConfigurationError(f"{name} must be a positive finite number")
    return parsed
