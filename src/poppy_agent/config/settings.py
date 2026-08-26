"""Environment-backed configuration for the Agent core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when required Agent configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Validated configuration needed to construct the Phase 2 Agent."""

    robot_mode: str
    robot_id: str
    network_interface: str | None = None
    robot_model: str | None = None
    robot_edition: str | None = None
    robot_firmware_version: str | None = None
    unitree_sdk_version: str | None = None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> AgentConfig:
        """Load and validate configuration from an environment mapping."""
        values = os.environ if environ is None else environ
        robot_mode = values.get("ROBOT_MODE", "").strip().lower()
        robot_id = values.get("POPPY_ROBOT_ID", "").strip()

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
        }
        if robot_mode == "unitree":
            for name, value in unitree_values.items():
                if not value:
                    raise ConfigurationError(f"{name} is required for ROBOT_MODE=unitree")

        return cls(
            robot_mode=robot_mode,
            robot_id=robot_id,
            network_interface=unitree_values["UNITREE_NETWORK_INTERFACE"] or None,
            robot_model=unitree_values["POPPY_ROBOT_MODEL"] or None,
            robot_edition=unitree_values["POPPY_ROBOT_EDITION"] or None,
            robot_firmware_version=unitree_values["POPPY_ROBOT_FIRMWARE_VERSION"] or None,
            unitree_sdk_version=unitree_values["UNITREE_SDK_VERSION"] or None,
        )
