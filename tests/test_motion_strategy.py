import math

import pytest

from poppy_agent.command import (
    CommandType,
    MoveDirection,
    MoveParameters,
    TurnDirection,
    TurnParameters,
)
from poppy_agent.execution import (
    MotionExecutionStrategy,
    MotionPlan,
    MotionProfile,
    MotionRateUnit,
    MotionStrategyError,
    MotionUnit,
    RecordingSleeper,
)
from poppy_agent.hardware import HardwareCommandIntent


def intent(command_type: CommandType, parameters: object) -> HardwareCommandIntent:
    return HardwareCommandIntent(
        sequence=3,
        source_block_id="motion-block",
        type=command_type,
        parameters=parameters,  # type: ignore[arg-type]
    )


def test_move_requires_an_explicit_profile() -> None:
    strategy = MotionExecutionStrategy()

    with pytest.raises(MotionStrategyError, match="explicit MotionProfile"):
        strategy.plan(intent(CommandType.MOVE, MoveParameters(MoveDirection.FORWARD, 1.0)))


@pytest.mark.parametrize(
    ("direction", "distance", "expected_duration"),
    [
        (MoveDirection.FORWARD, 1.5, 3.0),
        (MoveDirection.BACKWARD, 0.75, 1.5),
    ],
)
def test_move_plan_is_deterministic_and_retains_poppy_units(
    direction: MoveDirection,
    distance: float,
    expected_duration: float,
) -> None:
    strategy = MotionExecutionStrategy(MotionProfile(0.5, 90.0))

    plan = strategy.plan(intent(CommandType.MOVE, MoveParameters(direction, distance)))

    assert plan == MotionPlan(
        sequence=3,
        source_block_id="motion-block",
        command_type=CommandType.MOVE,
        direction=direction,
        magnitude=distance,
        magnitude_unit=MotionUnit.METERS,
        rate=0.5,
        rate_unit=MotionRateUnit.METERS_PER_SECOND,
        duration_seconds=expected_duration,
    )


@pytest.mark.parametrize(
    ("direction", "angle", "expected_duration"),
    [
        (TurnDirection.LEFT, 90.0, 1.0),
        (TurnDirection.RIGHT, 45.0, 0.5),
    ],
)
def test_turn_plan_is_deterministic_without_sign_or_unit_guessing(
    direction: TurnDirection,
    angle: float,
    expected_duration: float,
) -> None:
    strategy = MotionExecutionStrategy(MotionProfile(0.5, 90.0))

    plan = strategy.plan(intent(CommandType.TURN, TurnParameters(direction, angle)))

    assert plan.direction is direction
    assert plan.magnitude == angle
    assert plan.magnitude_unit is MotionUnit.DEGREES
    assert plan.rate_unit is MotionRateUnit.DEGREES_PER_SECOND
    assert plan.duration_seconds == expected_duration


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_motion_profile_rejects_invalid_rates(value: float) -> None:
    with pytest.raises(MotionStrategyError, match="rate must be a positive finite number"):
        MotionProfile(value, 90.0)


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_strategy_rejects_invalid_move_distance(value: float) -> None:
    strategy = MotionExecutionStrategy(MotionProfile(0.5, 90.0))

    with pytest.raises(
        MotionStrategyError,
        match="MOVE distance must be a positive finite number",
    ):
        strategy.plan(intent(CommandType.MOVE, MoveParameters(MoveDirection.FORWARD, value)))


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_strategy_rejects_invalid_turn_angle(value: float) -> None:
    strategy = MotionExecutionStrategy(MotionProfile(0.5, 90.0))

    with pytest.raises(
        MotionStrategyError,
        match="TURN angle must be a positive finite number",
    ):
        strategy.plan(intent(CommandType.TURN, TurnParameters(TurnDirection.LEFT, value)))


@pytest.mark.parametrize(
    ("command_type", "parameters", "linear_rate", "angular_rate"),
    [
        (
            CommandType.MOVE,
            MoveParameters(MoveDirection.FORWARD, 1.0e308),
            1.0e-308,
            90.0,
        ),
        (
            CommandType.MOVE,
            MoveParameters(MoveDirection.FORWARD, 1.0e-308),
            1.0e308,
            90.0,
        ),
        (
            CommandType.TURN,
            TurnParameters(TurnDirection.LEFT, 1.0e308),
            0.5,
            1.0e-308,
        ),
        (
            CommandType.TURN,
            TurnParameters(TurnDirection.LEFT, 1.0e-308),
            0.5,
            1.0e308,
        ),
    ],
)
def test_strategy_rejects_non_positive_or_non_finite_computed_duration(
    command_type: CommandType,
    parameters: object,
    linear_rate: float,
    angular_rate: float,
) -> None:
    strategy = MotionExecutionStrategy(MotionProfile(linear_rate, angular_rate))

    with pytest.raises(
        MotionStrategyError,
        match="motion duration must be a positive finite number",
    ):
        strategy.plan(intent(command_type, parameters))


def test_recording_sleeper_records_duration_without_wall_clock_wait() -> None:
    sleeper = RecordingSleeper()

    sleeper.sleep(2.5)
    sleeper.sleep(0.25)

    assert sleeper.durations == [2.5, 0.25]
