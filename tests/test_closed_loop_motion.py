"""Closed-loop MOVE/TURN on a simulated pose; nothing reaches DDS or a Robot."""

from __future__ import annotations

import math

import pytest

from poppy_agent.command import (
    CommandType,
    MoveDirection,
    MoveParameters,
    TurnDirection,
    TurnParameters,
)
from poppy_agent.execution.cancellation import (
    ExecutionCancellationToken,
    ExecutionCancelledError,
)
from poppy_agent.execution.motion import MotionExecutionStrategy, MotionProfile
from poppy_agent.hardware.boundary import HardwareCommandIntent
from poppy_agent.hardware.closed_loop import ClosedLoopLimits, MotionTracker, wrap_radians
from poppy_agent.hardware.unitree_sdk import (
    Go2MotionMapper,
    MotionStreamTiming,
    UnitreeMotionNotObservedError,
    UnitreeMotionOffCourseError,
    UnitreeMotionOutcomeUnknownError,
    UnitreeMotionTimeoutError,
    UnitreeSdkCommandClient,
    UnitreeTelemetryStaleError,
)
from poppy_agent.robot.adapter import SportStateSample
from sport_simulator import SimulatedRobot

LIMITS = ClosedLoopLimits()
STRATEGY = MotionExecutionStrategy(
    MotionProfile(linear_rate_meters_per_second=0.5, angular_rate_degrees_per_second=45.0)
)


class Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def wait(self, seconds: float, token: ExecutionCancellationToken | None) -> bool:
        self.now += seconds
        return token is not None and token.is_cancelled()


class Sport:
    def __init__(self, robot: SimulatedRobot) -> None:
        self.robot = robot
        self.moves: list[tuple[float, float, float]] = []
        self.stops = 0
        self.stop_result = 0
        self.after_move = None

    def Init(self) -> None:
        pass

    def Move(self, vx: float, vy: float, vyaw: float) -> int:
        self.moves.append((vx, vy, vyaw))
        self.robot.command(vx, vyaw)
        if self.after_move is not None:
            self.after_move()
        return 0

    def StopMove(self) -> int:
        self.stops += 1
        self.robot.stop()
        return self.stop_result


class Rig:
    def __init__(self, **robot_options: object) -> None:
        self.clock = Clock()
        self.robot = SimulatedRobot(self.clock.monotonic, **robot_options)  # type: ignore[arg-type]
        self.sport = Sport(self.robot)
        self.client = UnitreeSdkCommandClient(
            sdk_client=self.sport,
            motion_mapper=Go2MotionMapper(1),
            timing=MotionStreamTiming(
                monotonic=self.clock.monotonic, sleep=self.clock.sleep, wait=self.clock.wait
            ),
            sport_state=self.robot.state,
        )
        self.client.initialize()

    def move(self, meters: float, direction=MoveDirection.FORWARD, token=None) -> bool:
        intent = HardwareCommandIntent(0, "b", CommandType.MOVE, MoveParameters(direction, meters))
        return self.client.execute_motion_with_cancellation(STRATEGY.plan(intent), token)

    def turn(self, degrees: float, direction=TurnDirection.LEFT, token=None) -> bool:
        intent = HardwareCommandIntent(0, "b", CommandType.TURN, TurnParameters(direction, degrees))
        return self.client.execute_motion_with_cancellation(STRATEGY.plan(intent), token)

    @property
    def trace(self):
        return self.client.last_motion_trace

    def yaw_degrees(self) -> float:
        return math.degrees(self.robot.yaw)


@pytest.mark.parametrize("gain", [1.0, 0.8, 0.6])
def test_move_reaches_the_target_even_when_the_robot_undershoots_its_speed(gain) -> None:
    rig = Rig(gain=gain)
    assert rig.move(2.0) is True
    assert 2.0 - LIMITS.move_tolerance_meters - 0.02 <= rig.robot.x <= 2.0
    assert rig.sport.stops == 3


@pytest.mark.parametrize("gain", [1.0, 0.8])
def test_backward_move_goes_along_the_negative_heading(gain) -> None:
    rig = Rig(gain=gain, yaw_degrees=90.0)
    assert rig.move(1.0, MoveDirection.BACKWARD) is True
    assert rig.robot.y == pytest.approx(-1.0, abs=0.05)
    assert all(vx < 0 for vx, _, _ in rig.sport.moves)


@pytest.mark.parametrize(
    ("direction", "sign"), [(TurnDirection.LEFT, 1.0), (TurnDirection.RIGHT, -1.0)]
)
@pytest.mark.parametrize("gain", [1.0, 0.75])
def test_turn_reaches_the_target_within_tolerance(direction, sign, gain) -> None:
    rig = Rig(gain=gain)
    assert rig.turn(90.0, direction) is True
    assert rig.yaw_degrees() * sign == pytest.approx(90.0, abs=LIMITS.turn_tolerance_degrees)
    assert rig.sport.stops == 3


def test_move_slows_near_the_target_and_keeps_the_minimum_speed() -> None:
    rig = Rig()
    rig.move(2.0)
    speeds = [vx for vx, _, _ in rig.sport.moves]
    assert speeds[0] == pytest.approx(0.5)
    assert speeds == sorted(speeds, reverse=True)
    assert speeds[-1] == pytest.approx(LIMITS.min_linear_speed_meters_per_second)


def test_turn_slows_near_the_target_and_keeps_the_minimum_rate() -> None:
    rig = Rig()
    rig.turn(90.0)
    rates = [vyaw for _, _, vyaw in rig.sport.moves]
    assert rates[0] == pytest.approx(math.radians(45.0))
    assert rates == sorted(rates, reverse=True)
    assert rates[-1] == pytest.approx(math.radians(LIMITS.min_turn_rate_degrees_per_second))


def test_no_motion_fails_after_the_stall_window_with_stop_move() -> None:
    rig = Rig(gain=0.0)
    with pytest.raises(UnitreeMotionNotObservedError, match="로봇이 움직이지 않았어요"):
        rig.move(2.0)
    assert rig.trace.elapsed_seconds == pytest.approx(LIMITS.stall_window_seconds, abs=0.06)
    assert rig.sport.stops == 3


def test_no_yaw_change_fails_after_the_stall_window_with_stop_move() -> None:
    rig = Rig(gain=0.0)
    with pytest.raises(UnitreeMotionNotObservedError):
        rig.turn(90.0)
    assert rig.sport.stops == 3


def test_motion_the_wrong_way_is_not_progress() -> None:
    rig = Rig(gain=-1.0)
    with pytest.raises(UnitreeMotionNotObservedError):
        rig.turn(90.0)


def test_slow_robot_times_out_at_twice_the_plan_with_stop_move() -> None:
    rig = Rig(gain=0.2)
    with pytest.raises(UnitreeMotionTimeoutError):
        rig.move(2.0)
    assert rig.trace.elapsed_seconds == pytest.approx(8.0, abs=0.06)
    assert rig.sport.stops == 3


def test_short_command_is_not_failed_by_a_late_gait_start() -> None:
    rig = Rig(start_delay=0.6)
    assert rig.move(0.2) is True
    assert rig.client.last_motion_trace.elapsed_seconds > 0.8  # twice the 0.4 s plan


def test_short_command_still_has_a_time_limit() -> None:
    rig = Rig(gain=0.15)
    with pytest.raises(UnitreeMotionTimeoutError):
        rig.move(0.3)
    assert rig.trace.elapsed_seconds == pytest.approx(LIMITS.min_timeout_seconds, abs=0.06)


def test_stale_telemetry_before_the_start_sends_nothing() -> None:
    rig = Rig()
    rig.robot.stale_after_reads = 0
    with pytest.raises(UnitreeTelemetryStaleError):
        rig.move(1.0)
    assert rig.sport.moves == []
    assert rig.sport.stops == 0


def test_stale_telemetry_during_motion_stops_the_robot() -> None:
    rig = Rig()
    rig.robot.stale_after_reads = 5
    with pytest.raises(UnitreeTelemetryStaleError):
        rig.move(1.0)
    assert 0 < len(rig.sport.moves) < 10
    assert rig.sport.stops == 3


def test_sideways_travel_past_the_command_distance_fails_with_stop_move() -> None:
    rig = Rig(drift=2.0)
    with pytest.raises(UnitreeMotionOffCourseError):
        rig.move(1.0)
    assert rig.sport.stops == 3


def test_turn_across_the_wrap_keeps_its_real_size() -> None:
    rig = Rig(yaw_degrees=170.0)
    assert rig.turn(90.0) is True
    assert rig.yaw_degrees() - 170.0 == pytest.approx(90.0, abs=LIMITS.turn_tolerance_degrees)


def test_right_turn_across_the_negative_wrap() -> None:
    rig = Rig(yaw_degrees=-170.0)
    assert rig.turn(45.0, TurnDirection.RIGHT) is True
    assert rig.yaw_degrees() + 170.0 == pytest.approx(-45.0, abs=LIMITS.turn_tolerance_degrees)


def test_full_turn_does_not_finish_early_at_the_start_yaw() -> None:
    rig = Rig()
    assert rig.turn(360.0) is True
    assert rig.yaw_degrees() == pytest.approx(360.0, abs=LIMITS.turn_tolerance_degrees)


def test_cancellation_stops_the_robot() -> None:
    rig = Rig()
    token = ExecutionCancellationToken()
    rig.sport.after_move = lambda: token.cancel("test")
    with pytest.raises(ExecutionCancelledError):
        rig.move(1.0, token=token)
    assert rig.sport.stops == 3


def test_reached_target_without_a_stop_move_is_an_unknown_outcome() -> None:
    rig = Rig()
    rig.sport.stop_result = 1
    with pytest.raises(UnitreeMotionOutcomeUnknownError):
        rig.move(0.5)


def test_trace_records_the_achieved_distance_and_start_state() -> None:
    rig = Rig()
    rig.move(1.0)
    assert rig.trace.achieved_magnitude == pytest.approx(1.0, abs=0.05)
    assert (rig.trace.start_mode, rig.trace.start_gait_type) == (1, 1)


def test_nothing_is_retried_after_a_failure() -> None:
    rig = Rig(gain=0.0)
    with pytest.raises(UnitreeMotionNotObservedError):
        rig.move(1.0)
    calls = len(rig.sport.moves)
    assert calls == pytest.approx(LIMITS.stall_window_seconds / 0.05, abs=2)


@pytest.mark.parametrize(
    ("angle", "expected"),
    [(0.0, 0.0), (math.pi / 2, math.pi / 2), (3 * math.pi / 2, -math.pi / 2), (math.tau, 0.0)],
)
def test_wrap_radians(angle, expected) -> None:
    assert wrap_radians(angle) == pytest.approx(expected)


def test_tracker_counts_only_the_projection_on_the_start_heading() -> None:
    intent = HardwareCommandIntent(
        0, "b", CommandType.MOVE, MoveParameters(MoveDirection.FORWARD, 1.0)
    )
    start = SportStateSample(1.0, 1.0, math.pi / 2, 1, 1)
    tracker = MotionTracker(STRATEGY.plan(intent), start, 0.5, LIMITS)
    assert tracker.update(SportStateSample(1.3, 1.4, 0.0, 1, 1)) == pytest.approx(0.4)
