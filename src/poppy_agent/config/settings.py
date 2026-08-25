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

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> AgentConfig:
        """Load and validate configuration from an environment mapping."""
        values = os.environ if environ is None else environ
        robot_mode = values.get("ROBOT_MODE", "").strip().lower()
        robot_id = values.get("POPPY_ROBOT_ID", "").strip()

        if not robot_mode:
            raise ConfigurationError("ROBOT_MODE is required")
        if robot_mode != "mock":
            raise ConfigurationError("Phase 2 supports only ROBOT_MODE=mock")
        if not robot_id:
            raise ConfigurationError("POPPY_ROBOT_ID is required")

        return cls(robot_mode=robot_mode, robot_id=robot_id)
