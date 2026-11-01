"""Pure MOVE and TURN progress tracking on read-only sport state.

Nothing here touches the SDK.  MOVE progress is the distance projected on the
direction the Robot faced at the start; TURN progress is the accumulated signed
yaw, so it survives the +/-180 degree wrap.  Both count only toward the target, so
motion the wrong way is never progress.

The defaults are proposed values, to be confirmed against the recorded
``rt/sportmodestate`` data before any physical run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from poppy_agent.command import CommandType
from poppy_agent.execution.motion import MotionPlan
from poppy_agent.robot.adapter import SportStateSample


@dataclass(frozen=True, slots=True)
class ClosedLoopLimits:
    """Stop tolerances, slowdown zones and failure thresholds."""

    turn_tolerance_degrees: float = 3.0
    move_tolerance_meters: float = 0.03
    turn_slowdown_degrees: float = 30.0
    move_slowdown_meters: float = 0.5
    min_turn_rate_degrees_per_second: float = 20.0
    min_linear_speed_meters_per_second: float = 0.2
    stall_window_seconds: float = 1.5
    stall_min_turn_degrees: float = 3.0
    stall_min_move_meters: float = 0.05
    timeout_factor: float = 2.0
    # Twice the plan is too short for small commands: it would end before the stall
    # window and before the gait has started.
    min_timeout_seconds: float = 3.0
    # Straight-line travel beyond the target by this much means the Robot left the
    # projected line, even if the projection has not reached the target.
    move_off_course_margin_meters: float = 0.15


def wrap_radians(angle: float) -> float:
    """Return the equivalent angle in [-pi, pi)."""
    return (angle + math.pi) % math.tau - math.pi


class MotionTracker:
    """Follow one planned motion from its start sample."""

    def __init__(
        self,
        plan: MotionPlan,
        start: SportStateSample,
        command_sign: float,
        limits: ClosedLoopLimits,
    ) -> None:
        self._turn = plan.command_type is CommandType.TURN
        self._start = start
        self._sign = math.copysign(1.0, command_sign)
        self._limits = limits
        self._target = float(plan.magnitude)
        self._last_yaw = start.yaw_radians
        self._yaw_travel = 0.0
        self._straight_line_meters = 0.0
        self.progress = 0.0
        self.timeout_seconds = max(
            limits.timeout_factor * plan.duration_seconds, limits.min_timeout_seconds
        )
        minimum, slowdown = (
            (limits.min_turn_rate_degrees_per_second, limits.turn_slowdown_degrees)
            if self._turn
            else (limits.min_linear_speed_meters_per_second, limits.move_slowdown_meters)
        )
        self._min_scale = min(1.0, minimum / plan.rate)
        self._slowdown = slowdown

    def update(self, sample: SportStateSample) -> float:
        """Return the progress toward the target, in degrees or meters."""
        if self._turn:
            self._yaw_travel += wrap_radians(sample.yaw_radians - self._last_yaw)
            self._last_yaw = sample.yaw_radians
            self.progress = math.degrees(self._yaw_travel) * self._sign
        else:
            dx = sample.x_meters - self._start.x_meters
            dy = sample.y_meters - self._start.y_meters
            forward = dx * math.cos(self._start.yaw_radians) + dy * math.sin(
                self._start.yaw_radians
            )
            self.progress = forward * self._sign
            self._straight_line_meters = math.hypot(dx, dy)
        return self.progress

    @property
    def remaining(self) -> float:
        return self._target - self.progress

    @property
    def reached(self) -> bool:
        tolerance = (
            self._limits.turn_tolerance_degrees
            if self._turn
            else self._limits.move_tolerance_meters
        )
        return self.remaining <= tolerance

    @property
    def off_course(self) -> bool:
        return (
            not self._turn
            and self._straight_line_meters
            > self._target + self._limits.move_off_course_margin_meters
        )

    @property
    def stalled(self) -> bool:
        """Whether progress is below the minimum that must exist after the stall window."""
        minimum = (
            self._limits.stall_min_turn_degrees
            if self._turn
            else self._limits.stall_min_move_meters
        )
        return self.progress < minimum

    @property
    def speed_scale(self) -> float:
        """Fraction of the planned rate: full, then linear down to the minimum."""
        return max(self._min_scale, min(1.0, self.remaining / self._slowdown))


__all__ = ["ClosedLoopLimits", "MotionTracker", "wrap_radians"]
