"""Pure motion planning for Poppy distance and angle semantics.

The strategy produces a plan only. It does not select production safety values,
open a robot connection, or call a vendor SDK.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from poppy_agent.command import (
    CommandType,
    MoveDirection,
    MoveParameters,
    TurnDirection,
    TurnParameters,
)
from poppy_agent.execution.cancellation import ExecutionCancellationToken

if TYPE_CHECKING:
    from poppy_agent.hardware.boundary import HardwareCommandIntent


class MotionStrategyError(ValueError):
    """Raised when a motion intent cannot be planned safely."""


class MotionUnit(StrEnum):
    METERS = "meters"
    DEGREES = "degrees"


class MotionRateUnit(StrEnum):
    METERS_PER_SECOND = "meters/second"
    DEGREES_PER_SECOND = "degrees/second"


@dataclass(frozen=True, slots=True)
class MotionProfile:
    """Explicitly supplied planning rates; no production defaults exist."""

    linear_rate_meters_per_second: float
    angular_rate_degrees_per_second: float

    def __post_init__(self) -> None:
        _positive_finite(self.linear_rate_meters_per_second, "linear rate")
        _positive_finite(self.angular_rate_degrees_per_second, "angular rate")


@dataclass(frozen=True, slots=True)
class MotionPlan:
    """Deterministic plan retaining Poppy units and the explicit test rate."""

    sequence: int
    source_block_id: str
    command_type: CommandType
    direction: MoveDirection | TurnDirection
    magnitude: float
    magnitude_unit: MotionUnit
    rate: float
    rate_unit: MotionRateUnit
    duration_seconds: float


class MotionExecutionStrategy:
    """Plan MOVE/TURN only when an explicit profile has been supplied."""

    def __init__(self, profile: MotionProfile | None = None) -> None:
        self._profile = profile

    @property
    def configured(self) -> bool:
        """Return whether this strategy has an explicit planning profile."""
        return self._profile is not None

    def plan(self, intent: HardwareCommandIntent) -> MotionPlan:
        """Create a plan without converting to vendor-specific SDK arguments."""
        if self._profile is None:
            raise MotionStrategyError("an explicit MotionProfile is required")
        if intent.type is CommandType.MOVE and isinstance(intent.parameters, MoveParameters):
            _positive_finite(intent.parameters.distance_meters, "MOVE distance")
            rate = self._profile.linear_rate_meters_per_second
            duration = intent.parameters.distance_meters / rate
            _positive_finite(duration, "motion duration")
            return MotionPlan(
                sequence=intent.sequence,
                source_block_id=intent.source_block_id,
                command_type=intent.type,
                direction=intent.parameters.direction,
                magnitude=intent.parameters.distance_meters,
                magnitude_unit=MotionUnit.METERS,
                rate=rate,
                rate_unit=MotionRateUnit.METERS_PER_SECOND,
                duration_seconds=duration,
            )
        if intent.type is CommandType.TURN and isinstance(intent.parameters, TurnParameters):
            _positive_finite(intent.parameters.angle_degrees, "TURN angle")
            rate = self._profile.angular_rate_degrees_per_second
            duration = intent.parameters.angle_degrees / rate
            _positive_finite(duration, "motion duration")
            return MotionPlan(
                sequence=intent.sequence,
                source_block_id=intent.source_block_id,
                command_type=intent.type,
                direction=intent.parameters.direction,
                magnitude=intent.parameters.angle_degrees,
                magnitude_unit=MotionUnit.DEGREES,
                rate=rate,
                rate_unit=MotionRateUnit.DEGREES_PER_SECOND,
                duration_seconds=duration,
            )
        raise MotionStrategyError("motion intent type and parameters do not match")


class MotionSleeper(Protocol):
    """Timing boundary used after a fake motion dispatch."""

    def sleep(
        self,
        duration_seconds: float,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> None:
        """Wait for a planned duration; implementations may be non-blocking."""


class RecordingSleeper:
    """Test-only no-op sleeper that records requested durations."""

    def __init__(self) -> None:
        self.durations: list[float] = []

    def sleep(
        self,
        duration_seconds: float,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> None:
        """Record without waiting for wall-clock time."""
        self.durations.append(duration_seconds)


def _positive_finite(value: float, name: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
        raise MotionStrategyError(f"{name} must be a positive finite number")


__all__ = [
    "MotionExecutionStrategy",
    "MotionPlan",
    "MotionProfile",
    "MotionRateUnit",
    "MotionSleeper",
    "MotionStrategyError",
    "MotionUnit",
    "RecordingSleeper",
]
