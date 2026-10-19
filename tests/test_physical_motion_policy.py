import math

import pytest

from poppy_agent.command import CommandType, MoveDirection, TurnDirection
from poppy_agent.execution import (
    MotionPlan,
    MotionRateUnit,
    MotionUnit,
    PhysicalMotionPolicy,
    PhysicalMotionPolicyError,
)


def plan(
    command_type: CommandType = CommandType.MOVE,
    *,
    magnitude: float = 0.2,
    rate: float = 0.1,
    duration: float = 2.0,
) -> MotionPlan:
    return MotionPlan(
        sequence=0,
        source_block_id="fake-only",
        command_type=command_type,
        direction=(
            MoveDirection.FORWARD if command_type is CommandType.MOVE else TurnDirection.LEFT
        ),
        magnitude=magnitude,
        magnitude_unit=(
            MotionUnit.METERS if command_type is CommandType.MOVE else MotionUnit.DEGREES
        ),
        rate=rate,
        rate_unit=(
            MotionRateUnit.METERS_PER_SECOND
            if command_type is CommandType.MOVE
            else MotionRateUnit.DEGREES_PER_SECOND
        ),
        duration_seconds=duration,
    )


def test_test_only_policy_accepts_exact_boundaries() -> None:
    policy = PhysicalMotionPolicy.for_test()

    policy.validate(plan(magnitude=0.25, rate=0.1, duration=3.0))
    policy.validate(
        plan(
            CommandType.TURN,
            magnitude=15.0,
            rate=15.0,
            duration=1.0,
        )
    )


@pytest.mark.parametrize("value", [0.0, -0.1, math.nan, math.inf, -math.inf, True, "0.1"])
def test_policy_rejects_non_positive_or_non_finite_limits(value: object) -> None:
    with pytest.raises(PhysicalMotionPolicyError):
        PhysicalMotionPolicy(
            allowed_commands=frozenset({CommandType.MOVE}),
            max_move_distance_meters=value,  # type: ignore[arg-type]
            max_turn_angle_degrees=1.0,
            max_linear_rate_meters_per_second=1.0,
            max_angular_rate_degrees_per_second=1.0,
            max_duration_seconds=1.0,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"magnitude": 0.251}, "distance"),
        ({"rate": 0.101}, "rate"),
        ({"duration": 3.001}, "duration"),
    ],
)
def test_policy_rejects_move_values_above_explicit_test_limits(
    kwargs: dict[str, float], message: str
) -> None:
    with pytest.raises(PhysicalMotionPolicyError, match=message):
        PhysicalMotionPolicy.for_test().validate(plan(**kwargs))


def test_policy_rejects_command_not_on_allow_list() -> None:
    policy = PhysicalMotionPolicy(
        allowed_commands=frozenset({CommandType.TURN}),
        max_move_distance_meters=1.0,
        max_turn_angle_degrees=1.0,
        max_linear_rate_meters_per_second=1.0,
        max_angular_rate_degrees_per_second=1.0,
        max_duration_seconds=1.0,
    )

    with pytest.raises(PhysicalMotionPolicyError, match="allow-listed"):
        policy.validate(plan())
