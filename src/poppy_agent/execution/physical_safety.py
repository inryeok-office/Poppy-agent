"""Fail-closed, hardware-free policy for future physical motion dispatch.

The policy deliberately has no production defaults.  A reviewed caller must
provide every limit before MOVE or TURN can be exposed by a Unitree backend.
It neither imports a vendor SDK nor opens a connection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from poppy_agent.command import CommandType

from .motion import MotionPlan


class PhysicalMotionPolicyError(ValueError):
    """Raised when a motion intent is outside an explicit reviewed policy."""


def _positive_finite(value: float, name: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
        raise PhysicalMotionPolicyError(f"{name} must be a positive finite number")


@dataclass(frozen=True, slots=True)
class PhysicalMotionPolicy:
    """Explicit limits for hardware motion; no values are production-approved.

    Instances are intentionally supplied by a future approval workflow.  Test
    fixtures may use :meth:`for_test`; that helper is not an operational
    profile and is never loaded from the environment.
    """

    allowed_commands: frozenset[CommandType]
    max_move_distance_meters: float
    max_turn_angle_degrees: float
    max_linear_rate_meters_per_second: float
    max_angular_rate_degrees_per_second: float
    max_duration_seconds: float

    def __post_init__(self) -> None:
        if not self.allowed_commands or not self.allowed_commands <= {
            CommandType.MOVE,
            CommandType.TURN,
        }:
            raise PhysicalMotionPolicyError(
                "allowed_commands must explicitly contain MOVE and/or TURN"
            )
        for value, name in (
            (self.max_move_distance_meters, "max_move_distance_meters"),
            (self.max_turn_angle_degrees, "max_turn_angle_degrees"),
            (self.max_linear_rate_meters_per_second, "max_linear_rate_meters_per_second"),
            (self.max_angular_rate_degrees_per_second, "max_angular_rate_degrees_per_second"),
            (self.max_duration_seconds, "max_duration_seconds"),
        ):
            _positive_finite(value, name)

    @classmethod
    def for_test(cls) -> PhysicalMotionPolicy:
        """Return deliberately conservative fake-only values for unit tests."""
        return cls(
            allowed_commands=frozenset({CommandType.MOVE, CommandType.TURN}),
            max_move_distance_meters=0.25,
            max_turn_angle_degrees=15.0,
            max_linear_rate_meters_per_second=0.10,
            max_angular_rate_degrees_per_second=15.0,
            max_duration_seconds=3.0,
        )

    def validate(self, plan: MotionPlan) -> None:
        """Reject every plan outside explicit command, rate, magnitude, or time bounds."""
        if plan.command_type not in self.allowed_commands:
            raise PhysicalMotionPolicyError(f"{plan.command_type.value} is not allow-listed")
        for value, name in (
            (plan.magnitude, "motion magnitude"),
            (plan.rate, "motion rate"),
            (plan.duration_seconds, "motion duration"),
        ):
            _positive_finite(value, name)
        if plan.duration_seconds > self.max_duration_seconds:
            raise PhysicalMotionPolicyError("motion duration exceeds the explicit safety limit")
        if plan.command_type is CommandType.MOVE:
            if plan.magnitude > self.max_move_distance_meters:
                raise PhysicalMotionPolicyError("MOVE distance exceeds the explicit safety limit")
            if plan.rate > self.max_linear_rate_meters_per_second:
                raise PhysicalMotionPolicyError("MOVE rate exceeds the explicit safety limit")
        elif plan.command_type is CommandType.TURN:
            if plan.magnitude > self.max_turn_angle_degrees:
                raise PhysicalMotionPolicyError("TURN angle exceeds the explicit safety limit")
            if plan.rate > self.max_angular_rate_degrees_per_second:
                raise PhysicalMotionPolicyError("TURN rate exceeds the explicit safety limit")
        else:
            raise PhysicalMotionPolicyError("only MOVE and TURN may have a motion plan")


__all__ = ["PhysicalMotionPolicy", "PhysicalMotionPolicyError"]
