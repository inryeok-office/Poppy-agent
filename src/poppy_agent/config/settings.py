"""Environment-backed configuration for the Agent core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from poppy_agent.command import CommandType
from poppy_agent.execution import CapabilityEvidencePolicy, PhysicalMotionPolicy


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
    physical_motion_profile_name: str | None = None
    physical_motion_profile_version: str | None = None
    physical_motion_policy: PhysicalMotionPolicy | None = None
    physical_minimum_battery_percent: int | None = None
    physical_capability_evidence_policy: CapabilityEvidencePolicy | None = None

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

        physical_profile_name: str | None = None
        physical_profile_version: str | None = None
        physical_motion_policy: PhysicalMotionPolicy | None = None
        physical_minimum_battery_percent: int | None = None
        physical_capability_evidence_policy: CapabilityEvidencePolicy | None = None
        if physical_execution_enabled:
            physical_profile_name = _required(values, "POPPY_PHYSICAL_MOTION_PROFILE_NAME")
            physical_profile_version = _required(values, "POPPY_PHYSICAL_MOTION_PROFILE_VERSION")
            allowed_commands = _parse_motion_commands(
                _required(values, "POPPY_PHYSICAL_ALLOWED_COMMANDS")
            )
            physical_motion_policy = PhysicalMotionPolicy(
                allowed_commands=allowed_commands,
                max_move_distance_meters=_parse_positive_finite_float(
                    _required(values, "POPPY_PHYSICAL_MAX_MOVE_DISTANCE_METERS"),
                    "POPPY_PHYSICAL_MAX_MOVE_DISTANCE_METERS",
                ),
                max_turn_angle_degrees=_parse_positive_finite_float(
                    _required(values, "POPPY_PHYSICAL_MAX_TURN_ANGLE_DEGREES"),
                    "POPPY_PHYSICAL_MAX_TURN_ANGLE_DEGREES",
                ),
                max_linear_rate_meters_per_second=_parse_positive_finite_float(
                    _required(values, "POPPY_PHYSICAL_MAX_LINEAR_RATE_METERS_PER_SECOND"),
                    "POPPY_PHYSICAL_MAX_LINEAR_RATE_METERS_PER_SECOND",
                ),
                max_angular_rate_degrees_per_second=_parse_positive_finite_float(
                    _required(values, "POPPY_PHYSICAL_MAX_ANGULAR_RATE_DEGREES_PER_SECOND"),
                    "POPPY_PHYSICAL_MAX_ANGULAR_RATE_DEGREES_PER_SECOND",
                ),
                max_duration_seconds=_parse_positive_finite_float(
                    _required(values, "POPPY_PHYSICAL_MAX_COMMAND_DURATION_SECONDS"),
                    "POPPY_PHYSICAL_MAX_COMMAND_DURATION_SECONDS",
                ),
            )
            physical_minimum_battery_percent = _parse_battery_percent(
                _required(values, "POPPY_PHYSICAL_MIN_BATTERY_PERCENT"),
                "POPPY_PHYSICAL_MIN_BATTERY_PERCENT",
            )
            try:
                physical_capability_evidence_policy = CapabilityEvidencePolicy(
                    refresh_interval_seconds=_parse_positive_finite_float(
                        _required(values, "POPPY_PHYSICAL_CAPABILITY_REFRESH_INTERVAL_SECONDS"),
                        "POPPY_PHYSICAL_CAPABILITY_REFRESH_INTERVAL_SECONDS",
                    ),
                    ttl_seconds=_parse_positive_finite_float(
                        _required(values, "POPPY_PHYSICAL_CAPABILITY_TTL_SECONDS"),
                        "POPPY_PHYSICAL_CAPABILITY_TTL_SECONDS",
                    ),
                    request_timeout_seconds=_parse_positive_finite_float(
                        _required(values, "POPPY_PHYSICAL_CAPABILITY_REQUEST_TIMEOUT_SECONDS"),
                        "POPPY_PHYSICAL_CAPABILITY_REQUEST_TIMEOUT_SECONDS",
                    ),
                )
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc

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
            physical_motion_profile_name=physical_profile_name,
            physical_motion_profile_version=physical_profile_version,
            physical_motion_policy=physical_motion_policy,
            physical_minimum_battery_percent=physical_minimum_battery_percent,
            physical_capability_evidence_policy=physical_capability_evidence_policy,
        )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required when physical execution is enabled")
    return value


def _parse_motion_commands(value: str) -> frozenset[CommandType]:
    names = [item.strip() for item in value.split(",")]
    if not names or any(not name for name in names):
        raise ConfigurationError("POPPY_PHYSICAL_ALLOWED_COMMANDS must be a non-empty comma list")
    try:
        commands = frozenset(CommandType(name) for name in names)
    except ValueError as exc:
        raise ConfigurationError(
            "POPPY_PHYSICAL_ALLOWED_COMMANDS contains an unknown command"
        ) from exc
    if not commands or not commands <= {CommandType.MOVE, CommandType.TURN}:
        raise ConfigurationError(
            "POPPY_PHYSICAL_ALLOWED_COMMANDS must contain only MOVE and/or TURN"
        )
    return commands


def _parse_battery_percent(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer from 0 through 100") from exc
    if isinstance(parsed, bool) or str(parsed) != value or not 0 <= parsed <= 100:
        raise ConfigurationError(f"{name} must be an integer from 0 through 100")
    return parsed


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
