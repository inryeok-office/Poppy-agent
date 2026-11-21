"""Server-provided arena settings that may only *narrow* the Agent's approved limits.

The Agent's own environment (``POPPY_PHYSICAL_ARENA_*``, ``POPPY_PHYSICAL_START_*``,
``POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND``) is the approved baseline.  A remote value is
accepted only when every dimension is at least as strict as that baseline **and** inside the
hard caps compiled into this Agent.  Anything else is rejected as a whole and the baseline
stays.  Nothing else (expiry, speeds, total time, allowed commands, approval) is ever taken
from the Server.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from poppy_agent.config.open_motion import (
    MAX_ARENA_SIDE_METERS,
    MAX_MOVE_METERS_PER_COMMAND,
    MIN_ARENA_MARGIN_METERS,
    START_HEADING_DEGREES,
    OpenMotionSettings,
)

# One in-place turn needs a 0.8 m circle (Go2 body length 0.65 m); after the longest move
# the Robot must still be able to turn inside the usable area.
TURN_CIRCLE_DIAMETER_METERS = 0.8
MIN_USABLE_SIDE_METERS = 1.3
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class ArenaDecision:
    """Result of comparing a remote arena with the approved baseline."""

    settings: OpenMotionSettings
    accepted: bool
    reason: str | None = None


def narrow_arena(baseline: OpenMotionSettings, payload: object) -> ArenaDecision:
    """Return baseline narrowed by ``payload`` (Server ``data``), or the baseline with a reason."""
    reason = _reject_reason(baseline, payload)
    if reason is not None or not isinstance(payload, Mapping):
        return ArenaDecision(baseline, False, reason or "payload is not an object")
    width = _number(payload.get("widthM"))
    depth = _number(payload.get("depthM"))
    margin = _number(payload.get("marginM"))
    start_x = _number(payload.get("startXM"))
    start_y = _number(payload.get("startYM"))
    heading = START_HEADING_DEGREES[str(payload.get("startHeading"))]
    assert width is not None and depth is not None and margin is not None
    assert start_x is not None and start_y is not None
    usable_short = min(width, depth) - 2 * margin
    derived_cap = math.floor((usable_short - TURN_CIRCLE_DIAMETER_METERS) * 10 + _EPS) / 10
    per_command = min(
        baseline.max_move_meters_per_command, MAX_MOVE_METERS_PER_COMMAND, derived_cap
    )
    limits = payload.get("limits")
    if isinstance(limits, Mapping) and limits.get("maxMovePerCommandM") is not None:
        remote_cap = _number(limits.get("maxMovePerCommandM"))
        if remote_cap is None or remote_cap <= 0:
            return ArenaDecision(baseline, False, "limits.maxMovePerCommandM is invalid")
        per_command = min(per_command, remote_cap)
    if per_command < 0.1 - _EPS:
        return ArenaDecision(baseline, False, "no move distance fits the remote arena")
    return ArenaDecision(
        replace(
            baseline,
            arena_width_meters=width,
            arena_depth_meters=depth,
            arena_margin_meters=margin,
            start_x_meters=start_x,
            start_y_meters=start_y,
            start_heading_degrees=heading,
            max_move_meters_per_command=per_command,
        ),
        True,
    )


def _reject_reason(baseline: OpenMotionSettings, payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return "payload is not an object"
    width = _number(payload.get("widthM"))
    depth = _number(payload.get("depthM"))
    margin = _number(payload.get("marginM"))
    start_x = _number(payload.get("startXM"))
    start_y = _number(payload.get("startYM"))
    if None in (width, depth, margin, start_x, start_y):
        return "arena values are missing or not finite positive numbers"
    assert width is not None and depth is not None and margin is not None
    assert start_x is not None and start_y is not None
    if str(payload.get("startHeading")) not in START_HEADING_DEGREES:
        return "startHeading is not one of +X, -X, +Y, -Y"
    # Never wider than the approved baseline nor the compiled hard cap.
    side_cap = min(MAX_ARENA_SIDE_METERS, baseline.arena_width_meters)
    depth_cap = min(MAX_ARENA_SIDE_METERS, baseline.arena_depth_meters)
    if width > side_cap + _EPS:
        return "widthM is wider than the approved limit"
    if depth > depth_cap + _EPS:
        return "depthM is deeper than the approved limit"
    if margin < max(MIN_ARENA_MARGIN_METERS, baseline.arena_margin_meters) - _EPS:
        return "marginM is below the approved wall margin"
    if min(width, depth) - 2 * margin < MIN_USABLE_SIDE_METERS - _EPS:
        return "usable area is too small"
    if not (margin - _EPS <= start_x <= width - margin + _EPS) or not (
        margin - _EPS <= start_y <= depth - margin + _EPS
    ):
        return "start pose is outside the wall margin"
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


__all__ = ["ArenaDecision", "narrow_arena"]
