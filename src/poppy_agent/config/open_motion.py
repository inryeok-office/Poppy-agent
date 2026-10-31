"""Time-boxed open motion trial settings (``controlled_motion_open``).

There are no code defaults.  Missing or out-of-range values do not raise: they
are returned as stable issue strings so the Agent stays heartbeat-only and
reports why physical execution is blocked.  Hard caps below are the physical
safety limits approved for one Execution; configuration may be stricter only.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from poppy_agent.config.physical_trial import GO2_MAX_YAW_RATE_RADIANS_PER_SECOND

CONTROLLED_MOTION_OPEN_MODE = "controlled_motion_open"

# Per-Execution physical safety limits (teacher approval 2026-10-28, open trial).
MAX_LINEAR_SPEED_METERS_PER_SECOND = 1.0
MAX_MOVE_METERS_PER_COMMAND = 3.0
MAX_TURN_DEGREES_PER_COMMAND = 360.0
MAX_TOTAL_SECONDS_PER_EXECUTION = 120.0
MAX_ARENA_SIDE_METERS = 4.0
MIN_ARENA_MARGIN_METERS = 0.4
MAX_SETTLE_SECONDS = 15.0
# The approval window is at most eight hours (teacher approval extended on 2026-10-29);
# a longer expiry is a configuration error.
MAX_APPROVAL_WINDOW = timedelta(hours=8, minutes=5)

# Server presetCode -> official Go2 SportClient method (unitree_sdk2py/go2/sport/
# sport_client.py: Hello 1016, Stretch 1017, Dance1 1022, Heart 1036).  Jump,
# flip, pounce and other acrobatic actions are never mapped.
PRESET_SDK_METHODS: Mapping[str, str] = {
    "HELLO": "Hello",
    "STRETCH": "Stretch",
    "HEART": "Heart",
    "DANCE1": "Dance1",
}

# Start heading -> degrees clockwise from +Y, the arena's forward axis.
START_HEADING_DEGREES: Mapping[str, float] = {"+Y": 0.0, "+X": 90.0, "-Y": 180.0, "-X": 270.0}

OPEN_MOTION_COMMANDS = frozenset({"MOVE", "TURN", "POSTURE", "PRESET"})

OPEN_MOTION_ENVIRONMENT_KEYS = (
    "POPPY_PHYSICAL_TRIAL_MODE",
    "POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S",
    "POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND",
    "POPPY_PHYSICAL_ARENA_WIDTH_M",
    "POPPY_PHYSICAL_ARENA_DEPTH_M",
    "POPPY_PHYSICAL_ARENA_MARGIN_M",
    "POPPY_PHYSICAL_START_X_M",
    "POPPY_PHYSICAL_START_Y_M",
    "POPPY_PHYSICAL_START_HEADING",
    "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S",
    "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND",
    "POPPY_PHYSICAL_MAX_TOTAL_SECONDS",
    "POPPY_PHYSICAL_POSTURE_SETTLE_SECONDS",
    "POPPY_PHYSICAL_PRESET_SETTLE_SECONDS",
    "POPPY_PHYSICAL_ALLOWED_COMMANDS",
    "POPPY_PHYSICAL_ALLOWED_PRESETS",
    "POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN",
    "POPPY_PHYSICAL_APPROVAL_REF",
    "POPPY_PHYSICAL_TRIAL_EXPIRES_AT",
)

_APPROVAL_REF_MAX_LENGTH = 120


@dataclass(frozen=True, slots=True)
class OpenMotionSettings:
    """Validated per-Execution limits for the time-boxed open motion trial."""

    mode: str
    linear_speed_meters_per_second: float
    max_move_meters_per_command: float
    arena_width_meters: float
    arena_depth_meters: float
    arena_margin_meters: float
    start_x_meters: float
    start_y_meters: float
    start_heading_degrees: float
    turn_rate_degrees_per_second: float
    max_turn_degrees_per_command: float
    max_total_seconds: float
    posture_settle_seconds: float
    preset_settle_seconds: float
    allowed_commands: frozenset[str]
    allowed_presets: frozenset[str]
    turn_left_yaw_sign: int
    approval_ref: str
    expires_at: datetime


def load_open_motion_settings(
    values: Mapping[str, str],
    *,
    now: Callable[[], datetime],
) -> tuple[OpenMotionSettings | None, tuple[str, ...]]:
    """Return validated settings, or ``None`` with every detected issue."""
    raw = {key: values.get(key, "").strip() for key in OPEN_MOTION_ENVIRONMENT_KEYS}
    issues = [f"{key} is required" for key, value in raw.items() if not value]

    mode = raw["POPPY_PHYSICAL_TRIAL_MODE"]
    if mode and mode != CONTROLLED_MOTION_OPEN_MODE:
        issues.append(f"POPPY_PHYSICAL_TRIAL_MODE must be {CONTROLLED_MOTION_OPEN_MODE}")

    speed = _bounded(
        raw, "POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S", MAX_LINEAR_SPEED_METERS_PER_SECOND, issues
    )
    move_per_command = _bounded(
        raw, "POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND", MAX_MOVE_METERS_PER_COMMAND, issues
    )
    arena_width = _bounded(raw, "POPPY_PHYSICAL_ARENA_WIDTH_M", MAX_ARENA_SIDE_METERS, issues)
    arena_depth = _bounded(raw, "POPPY_PHYSICAL_ARENA_DEPTH_M", MAX_ARENA_SIDE_METERS, issues)
    arena_margin = _bounded(raw, "POPPY_PHYSICAL_ARENA_MARGIN_M", MAX_ARENA_SIDE_METERS, issues)
    if arena_margin is not None and arena_margin < MIN_ARENA_MARGIN_METERS - 1e-9:
        issues.append(
            "POPPY_PHYSICAL_ARENA_MARGIN_M is below the approved minimum of "
            f"{MIN_ARENA_MARGIN_METERS:g}"
        )
    start_x = _bounded(raw, "POPPY_PHYSICAL_START_X_M", MAX_ARENA_SIDE_METERS, issues)
    start_y = _bounded(raw, "POPPY_PHYSICAL_START_Y_M", MAX_ARENA_SIDE_METERS, issues)
    if (
        arena_width is not None
        and arena_depth is not None
        and arena_margin is not None
        and start_x is not None
        and start_y is not None
    ):
        if not (
            arena_margin - 1e-9 <= start_x <= arena_width - arena_margin + 1e-9
            and arena_margin - 1e-9 <= start_y <= arena_depth - arena_margin + 1e-9
        ):
            issues.append("POPPY_PHYSICAL_START_X_M/Y_M must be inside the arena margin")
    heading_value = raw["POPPY_PHYSICAL_START_HEADING"]
    start_heading = START_HEADING_DEGREES.get(heading_value)
    if heading_value and start_heading is None:
        issues.append("POPPY_PHYSICAL_START_HEADING must be one of +X, -X, +Y, -Y")
    rate = _bounded(
        raw,
        "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S",
        math.degrees(GO2_MAX_YAW_RATE_RADIANS_PER_SECOND),
        issues,
    )
    turn_per_command = _bounded(
        raw, "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND", MAX_TURN_DEGREES_PER_COMMAND, issues
    )
    total_seconds = _bounded(
        raw, "POPPY_PHYSICAL_MAX_TOTAL_SECONDS", MAX_TOTAL_SECONDS_PER_EXECUTION, issues
    )
    posture_settle = _bounded(
        raw, "POPPY_PHYSICAL_POSTURE_SETTLE_SECONDS", MAX_SETTLE_SECONDS, issues
    )
    preset_settle = _bounded(
        raw, "POPPY_PHYSICAL_PRESET_SETTLE_SECONDS", MAX_SETTLE_SECONDS, issues
    )

    allowed_commands = _code_set(
        raw, "POPPY_PHYSICAL_ALLOWED_COMMANDS", OPEN_MOTION_COMMANDS, issues
    )
    allowed_presets = _code_set(
        raw, "POPPY_PHYSICAL_ALLOWED_PRESETS", frozenset(PRESET_SDK_METHODS), issues
    )

    sign_value = raw["POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN"]
    sign = {"+1": 1, "1": 1, "-1": -1}.get(sign_value)
    if sign_value and sign is None:
        issues.append("POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN must be +1 or -1")

    approval_ref = raw["POPPY_PHYSICAL_APPROVAL_REF"]
    if approval_ref and (
        len(approval_ref) > _APPROVAL_REF_MAX_LENGTH or not approval_ref.isprintable()
    ):
        issues.append("POPPY_PHYSICAL_APPROVAL_REF must be printable and at most 120 characters")

    expires_at = _expiry(raw["POPPY_PHYSICAL_TRIAL_EXPIRES_AT"], now(), issues)

    if issues:
        return None, tuple(issues)
    assert speed is not None and move_per_command is not None
    assert arena_width is not None and arena_depth is not None and arena_margin is not None
    assert start_x is not None and start_y is not None and start_heading is not None
    assert rate is not None and turn_per_command is not None and total_seconds is not None
    assert posture_settle is not None and preset_settle is not None and sign is not None
    assert allowed_commands is not None and allowed_presets is not None
    assert expires_at is not None
    return (
        OpenMotionSettings(
            mode=mode,
            linear_speed_meters_per_second=speed,
            max_move_meters_per_command=move_per_command,
            arena_width_meters=arena_width,
            arena_depth_meters=arena_depth,
            arena_margin_meters=arena_margin,
            start_x_meters=start_x,
            start_y_meters=start_y,
            start_heading_degrees=start_heading,
            turn_rate_degrees_per_second=rate,
            max_turn_degrees_per_command=turn_per_command,
            max_total_seconds=total_seconds,
            posture_settle_seconds=posture_settle,
            preset_settle_seconds=preset_settle,
            allowed_commands=allowed_commands,
            allowed_presets=allowed_presets,
            turn_left_yaw_sign=sign,
            approval_ref=approval_ref,
            expires_at=expires_at,
        ),
        (),
    )


def _bounded(raw: Mapping[str, str], key: str, upper: float, issues: list[str]) -> float | None:
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
    if parsed > upper + 1e-9:
        issues.append(f"{key} exceeds the approved limit of {upper:g}")
        return None
    return parsed


def _code_set(
    raw: Mapping[str, str], key: str, allowed: frozenset[str], issues: list[str]
) -> frozenset[str] | None:
    value = raw[key]
    if not value:
        return None
    codes = [code.strip() for code in value.split(",")]
    if any(not code for code in codes) or len(set(codes)) != len(codes):
        issues.append(f"{key} must be a comma-separated list without blanks or duplicates")
        return None
    unknown = sorted(set(codes) - allowed)
    if unknown:
        issues.append(f"{key} contains unsupported values: {','.join(unknown)}")
        return None
    return frozenset(codes)


def _expiry(value: str, now: datetime, issues: list[str]) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        issues.append("POPPY_PHYSICAL_TRIAL_EXPIRES_AT must be an ISO 8601 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append("POPPY_PHYSICAL_TRIAL_EXPIRES_AT must include a UTC offset")
        return None
    if parsed <= now:
        issues.append("POPPY_PHYSICAL_TRIAL_EXPIRES_AT is not in the future")
        return None
    if parsed - now > MAX_APPROVAL_WINDOW:
        issues.append("POPPY_PHYSICAL_TRIAL_EXPIRES_AT exceeds the eight-hour approval window")
        return None
    return parsed


__all__ = [
    "CONTROLLED_MOTION_OPEN_MODE",
    "MAX_ARENA_SIDE_METERS",
    "MAX_LINEAR_SPEED_METERS_PER_SECOND",
    "MAX_MOVE_METERS_PER_COMMAND",
    "MAX_TOTAL_SECONDS_PER_EXECUTION",
    "MAX_TURN_DEGREES_PER_COMMAND",
    "MIN_ARENA_MARGIN_METERS",
    "OPEN_MOTION_COMMANDS",
    "OPEN_MOTION_ENVIRONMENT_KEYS",
    "OpenMotionSettings",
    "PRESET_SDK_METHODS",
    "START_HEADING_DEGREES",
    "load_open_motion_settings",
]
