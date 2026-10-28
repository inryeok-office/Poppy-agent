"""Controlled physical trial settings loaded only from explicit environment values.

There are no code defaults.  Missing or out-of-range values do not raise: they
are returned as stable issue strings so the Agent can stay alive in a
heartbeat-only state and report why physical execution is blocked.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

CONTROLLED_TURN_TRIAL_MODE = "controlled_turn_v1"

# Operator-provided GO2 EDU AI Motion interface (< V1.1.6) vyaw range, not a
# hardware readback.
GO2_MAX_YAW_RATE_RADIANS_PER_SECOND = 0.8

# Administrator limits relayed by the user for the whole trial.  Configuration
# may be stricter but never looser.
ADMIN_MAX_TOTAL_TURN_DEGREES = 360.0
ADMIN_MAX_TOTAL_MOTION_SECONDS = 60.0

_APPROVAL_REF_MAX_LENGTH = 120

PHYSICAL_TRIAL_ENVIRONMENT_KEYS = (
    "POPPY_PHYSICAL_TRIAL_MODE",
    "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S",
    "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND",
    "POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG",
    "POPPY_PHYSICAL_MAX_TOTAL_SECONDS",
    "POPPY_PHYSICAL_MAX_COMMANDS",
    "POPPY_PHYSICAL_ALLOWED_COMMANDS",
    "POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN",
    "POPPY_PHYSICAL_APPROVAL_REF",
)


@dataclass(frozen=True, slots=True)
class PhysicalTrialSettings:
    """Validated controlled TURN trial budget and approval reference."""

    mode: str
    turn_rate_degrees_per_second: float
    max_turn_degrees_per_command: float
    max_total_turn_degrees: float
    max_total_seconds: float
    max_commands: int
    turn_left_yaw_sign: int
    approval_ref: str

    @property
    def turn_rate_radians_per_second(self) -> float:
        return math.radians(self.turn_rate_degrees_per_second)


def load_physical_trial_settings(
    values: Mapping[str, str],
) -> tuple[PhysicalTrialSettings | None, tuple[str, ...]]:
    """Return validated settings, or ``None`` with every detected issue."""
    raw = {key: values.get(key, "").strip() for key in PHYSICAL_TRIAL_ENVIRONMENT_KEYS}
    issues = [f"{key} is required" for key, value in raw.items() if not value]

    mode = raw["POPPY_PHYSICAL_TRIAL_MODE"]
    if mode and mode != CONTROLLED_TURN_TRIAL_MODE:
        issues.append(f"POPPY_PHYSICAL_TRIAL_MODE must be {CONTROLLED_TURN_TRIAL_MODE}")

    rate = _positive_number(raw, "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S", issues)
    per_command = _positive_number(raw, "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND", issues)
    total_turn = _positive_number(raw, "POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG", issues)
    total_seconds = _positive_number(raw, "POPPY_PHYSICAL_MAX_TOTAL_SECONDS", issues)
    max_commands = _positive_integer(raw, "POPPY_PHYSICAL_MAX_COMMANDS", issues)

    if rate is not None and math.radians(rate) > GO2_MAX_YAW_RATE_RADIANS_PER_SECOND:
        issues.append("POPPY_PHYSICAL_TURN_RATE_DEG_PER_S exceeds the GO2 0.8 rad/s yaw limit")
    if total_turn is not None and total_turn > ADMIN_MAX_TOTAL_TURN_DEGREES:
        issues.append("POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG exceeds the administrator limit of 360")
    if total_seconds is not None and total_seconds > ADMIN_MAX_TOTAL_MOTION_SECONDS:
        issues.append("POPPY_PHYSICAL_MAX_TOTAL_SECONDS exceeds the administrator limit of 60")
    if per_command is not None and total_turn is not None and per_command > total_turn:
        issues.append(
            "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND exceeds POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG"
        )
    if (
        per_command is not None
        and rate is not None
        and total_seconds is not None
        and per_command / rate > total_seconds
    ):
        issues.append("one maximum TURN would exceed POPPY_PHYSICAL_MAX_TOTAL_SECONDS")

    allowed = raw["POPPY_PHYSICAL_ALLOWED_COMMANDS"]
    if allowed and allowed != "TURN":
        issues.append("POPPY_PHYSICAL_ALLOWED_COMMANDS must be exactly TURN")

    sign_value = raw["POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN"]
    sign = {"+1": 1, "1": 1, "-1": -1}.get(sign_value)
    if sign_value and sign is None:
        issues.append("POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN must be +1 or -1")

    approval_ref = raw["POPPY_PHYSICAL_APPROVAL_REF"]
    if approval_ref and (
        len(approval_ref) > _APPROVAL_REF_MAX_LENGTH or not approval_ref.isprintable()
    ):
        issues.append("POPPY_PHYSICAL_APPROVAL_REF must be printable and at most 120 characters")

    if issues:
        return None, tuple(issues)
    assert rate is not None and per_command is not None and total_turn is not None
    assert total_seconds is not None and max_commands is not None and sign is not None
    return (
        PhysicalTrialSettings(
            mode=mode,
            turn_rate_degrees_per_second=rate,
            max_turn_degrees_per_command=per_command,
            max_total_turn_degrees=total_turn,
            max_total_seconds=total_seconds,
            max_commands=max_commands,
            turn_left_yaw_sign=sign,
            approval_ref=approval_ref,
        ),
        (),
    )


def _positive_number(raw: Mapping[str, str], key: str, issues: list[str]) -> float | None:
    value = raw[key]
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        parsed = math.nan
    if not math.isfinite(parsed) or parsed <= 0:
        issues.append(f"{key} must be a positive finite number")
        return None
    return parsed


def _positive_integer(raw: Mapping[str, str], key: str, issues: list[str]) -> int | None:
    value = raw[key]
    if not value:
        return None
    if not value.isdigit() or int(value) < 1:
        issues.append(f"{key} must be a positive integer")
        return None
    return int(value)


__all__ = [
    "ADMIN_MAX_TOTAL_MOTION_SECONDS",
    "ADMIN_MAX_TOTAL_TURN_DEGREES",
    "CONTROLLED_TURN_TRIAL_MODE",
    "GO2_MAX_YAW_RATE_RADIANS_PER_SECOND",
    "PHYSICAL_TRIAL_ENVIRONMENT_KEYS",
    "PhysicalTrialSettings",
    "load_physical_trial_settings",
]
