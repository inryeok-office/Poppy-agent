"""controlled_motion_open trial: configuration, guard, SDK mapping and wiring with fakes only."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

import poppy_agent.main as main_module
from poppy_agent.command import (
    CommandType,
    HighLevelCommand,
    HighLevelCommandProgram,
    MoveDirection,
    MoveParameters,
    Posture,
    PostureParameters,
    PresetParameters,
    StopParameters,
    TurnDirection,
    TurnParameters,
    WaitParameters,
)
from poppy_agent.config import AgentConfig, OpenMotionSettings
from poppy_agent.config.open_motion import (
    OPEN_MOTION_ENVIRONMENT_KEYS,
    PRESET_SDK_METHODS,
    load_open_motion_settings,
)
from poppy_agent.execution import ExecutionCancellationToken, ExecutionStatus, ExecutionTask
from poppy_agent.execution.open_motion import OpenMotionGuard, OpenMotionGuardError
from poppy_agent.hardware import OpenMotionExecution, create_open_motion_executor
from poppy_agent.hardware.unitree_sdk import MotionStreamTiming

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")
EXECUTION_ID = UUID("00000000-0000-0000-0000-0000000000e2")
KST = timezone(timedelta(hours=9))
START = datetime(2026, 10, 28, 20, 20, tzinfo=KST)
EXPIRES = START + timedelta(hours=2)

OPEN_ENV = {
    "POPPY_PHYSICAL_TRIAL_MODE": "controlled_motion_open",
    "POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S": "0.5",
    "POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND": "3.0",
    "POPPY_PHYSICAL_ARENA_WIDTH_M": "4.0",
    "POPPY_PHYSICAL_ARENA_DEPTH_M": "4.0",
    "POPPY_PHYSICAL_ARENA_MARGIN_M": "0.4",
    "POPPY_PHYSICAL_START_X_M": "2.0",
    "POPPY_PHYSICAL_START_Y_M": "0.4",
    "POPPY_PHYSICAL_START_HEADING": "+Y",
    "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S": "45",
    "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND": "360",
    "POPPY_PHYSICAL_MAX_TOTAL_SECONDS": "120",
    "POPPY_PHYSICAL_POSTURE_SETTLE_SECONDS": "3",
    "POPPY_PHYSICAL_PRESET_SETTLE_SECONDS": "5",
    "POPPY_PHYSICAL_ALLOWED_COMMANDS": "MOVE,TURN,POSTURE,PRESET",
    "POPPY_PHYSICAL_ALLOWED_PRESETS": "HELLO,STRETCH,HEART,DANCE1",
    "POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN": "+1",
    "POPPY_PHYSICAL_APPROVAL_REF": "test-open-approval",
    "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": EXPIRES.isoformat(),
}


def open_settings(**overrides: str) -> OpenMotionSettings:
    settings, issues = load_open_motion_settings({**OPEN_ENV, **overrides}, now=lambda: START)
    assert issues == ()
    assert settings is not None
    return settings


def issues_for(**overrides: str) -> tuple[str, ...]:
    settings, issues = load_open_motion_settings({**OPEN_ENV, **overrides}, now=lambda: START)
    assert settings is None
    return issues


class FakeClock:
    """Fake monotonic clock and wall clock; waits advance both."""

    def __init__(self, *, cancel_after_waits: int | None = None) -> None:
        self.now = 100.0
        self.wall = START
        self.waits: list[float] = []
        self.cancel_after_waits = cancel_after_waits

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def wait(self, seconds: float, token: ExecutionCancellationToken | None) -> bool:
        self.waits.append(seconds)
        self.advance(seconds)
        if token is None:
            return False
        if self.cancel_after_waits is not None and len(self.waits) >= self.cancel_after_waits:
            token.cancel("test cancellation")
        return token.is_cancelled()

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.wall += timedelta(seconds=seconds)

    def wall_now(self) -> datetime:
        return self.wall


class FakeSportClient:
    """Inert SportClient double; nothing here reaches DDS or a Robot."""

    def __init__(self, clock: FakeClock, *, move_error_at: int | None = None) -> None:
        self.clock = clock
        self.move_error_at = move_error_at
        self.calls: list[tuple[str, tuple[float, ...]]] = []

    def _record(self, name: str, *args: float) -> int:
        self.calls.append((name, args))
        return 0

    def Init(self) -> None:
        self.calls.append(("Init", ()))

    def Move(self, vx: float, vy: float, vyaw: float) -> int:
        if self.move_error_at == len(self.moves):
            self.calls.append(("Move", (vx, vy, vyaw)))
            raise RuntimeError("simulated transport failure")
        return self._record("Move", vx, vy, vyaw)

    def StopMove(self) -> int:
        return self._record("StopMove")

    def Sit(self) -> int:
        return self._record("Sit")

    def StandUp(self) -> int:
        return self._record("StandUp")

    def BalanceStand(self) -> int:
        return self._record("BalanceStand")

    def RiseSit(self) -> int:
        return self._record("RiseSit")

    def Hello(self) -> int:
        return self._record("Hello")

    def Stretch(self) -> int:
        return self._record("Stretch")

    def Heart(self) -> int:
        return self._record("Heart")

    def Dance1(self) -> int:
        return self._record("Dance1")

    def FrontFlip(self) -> int:
        raise AssertionError("FrontFlip must never be reachable")

    def Close(self) -> None:
        self.calls.append(("Close", ()))

    @property
    def moves(self) -> list[tuple[str, tuple[float, ...]]]:
        return [call for call in self.calls if call[0] == "Move"]

    def names(self) -> list[str]:
        """Calls with consecutive Move entries collapsed, excluding Init."""
        collapsed: list[str] = []
        for name, _args in self.calls:
            if name == "Init" or (name == "Move" and collapsed and collapsed[-1] == "Move"):
                continue
            collapsed.append(name)
        return collapsed


def build(
    clock: FakeClock,
    sport: FakeSportClient,
    *,
    settings: OpenMotionSettings | None = None,
    telemetry_fresh: bool = True,
) -> OpenMotionExecution:
    return create_open_motion_executor(
        robot_id=ROBOT_ID,
        physical_execution_enabled=True,
        settings=settings or open_settings(),
        telemetry_fresh=lambda: telemetry_fresh,
        sport_client_factory=lambda: sport,
        timing=MotionStreamTiming(monotonic=clock.monotonic, sleep=clock.sleep, wait=clock.wait),
        now=clock.wall_now,
    )


def move(distance: float, direction: MoveDirection = MoveDirection.FORWARD) -> tuple:
    return (CommandType.MOVE, MoveParameters(direction, distance))


def turn(angle: float, direction: TurnDirection = TurnDirection.RIGHT) -> tuple:
    return (CommandType.TURN, TurnParameters(direction, angle))


def posture(value: Posture) -> tuple:
    return (CommandType.POSTURE, PostureParameters(value))


def wait(seconds: float) -> tuple:
    return (CommandType.WAIT, WaitParameters(seconds))


def preset(code: str) -> tuple:
    return (CommandType.PRESET, PresetParameters(code))


STOP = (CommandType.STOP, StopParameters())


def task(*commands: tuple) -> ExecutionTask:
    built = tuple(
        HighLevelCommand(index, f"block-{index}", command_type, parameters)
        for index, (command_type, parameters) in enumerate(commands)
    )
    return ExecutionTask(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        protocol_version=1,
        command_program=HighLevelCommandProgram(1, built),
    )


def run(trial: OpenMotionExecution, *commands: tuple):
    return trial.executor.execute(task(*commands), ExecutionCancellationToken())


# --- configuration -------------------------------------------------------------


def test_complete_open_configuration_loads_exact_values() -> None:
    settings = open_settings()
    assert settings.linear_speed_meters_per_second == 0.5
    assert settings.arena_width_meters == 4.0
    assert settings.arena_depth_meters == 4.0
    assert settings.arena_margin_meters == 0.4
    assert (settings.start_x_meters, settings.start_y_meters) == (2.0, 0.4)
    assert settings.start_heading_degrees == 0.0
    assert settings.max_total_seconds == 120.0
    assert settings.turn_rate_degrees_per_second == 45.0
    assert settings.allowed_presets == frozenset({"HELLO", "STRETCH", "HEART", "DANCE1"})
    assert settings.expires_at == EXPIRES


@pytest.mark.parametrize("key", OPEN_MOTION_ENVIRONMENT_KEYS)
def test_every_open_key_is_required_without_defaults(key: str) -> None:
    assert f"{key} is required" in issues_for(**{key: ""})


@pytest.mark.parametrize(
    ("key", "value", "fragment"),
    [
        ("POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S", "1.01", "approved limit of 1"),
        ("POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND", "3.1", "approved limit of 3"),
        ("POPPY_PHYSICAL_ARENA_WIDTH_M", "6.1", "approved limit of 6"),
        ("POPPY_PHYSICAL_ARENA_DEPTH_M", "6.1", "approved limit of 6"),
        ("POPPY_PHYSICAL_ARENA_MARGIN_M", "0.3", "approved minimum of 0.4"),
        ("POPPY_PHYSICAL_START_X_M", "3.7", "inside the arena margin"),
        ("POPPY_PHYSICAL_START_Y_M", "0.3", "inside the arena margin"),
        ("POPPY_PHYSICAL_START_HEADING", "UP", "one of +X"),
        ("POPPY_PHYSICAL_MAX_TOTAL_SECONDS", "121", "approved limit of 120"),
        ("POPPY_PHYSICAL_TURN_RATE_DEG_PER_S", "46", "approved limit of 45.8"),
        ("POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND", "361", "approved limit of 360"),
        ("POPPY_PHYSICAL_POSTURE_SETTLE_SECONDS", "0", "positive finite"),
        ("POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S", "nan", "positive finite"),
        ("POPPY_PHYSICAL_ALLOWED_PRESETS", "HELLO,FRONTFLIP", "unsupported values: FRONTFLIP"),
        ("POPPY_PHYSICAL_ALLOWED_COMMANDS", "MOVE,JUMP", "unsupported values: JUMP"),
        ("POPPY_PHYSICAL_ALLOWED_COMMANDS", "MOVE,MOVE", "without blanks or duplicates"),
        ("POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN", "2", "+1 or -1"),
        ("POPPY_PHYSICAL_TRIAL_MODE", "controlled_motion_v9", "must be controlled_motion_open"),
        ("POPPY_PHYSICAL_TRIAL_EXPIRES_AT", "2026-10-28T22:20:00", "UTC offset"),
        ("POPPY_PHYSICAL_TRIAL_EXPIRES_AT", "tomorrow", "ISO 8601"),
        ("POPPY_PHYSICAL_TRIAL_EXPIRES_AT", START.isoformat(), "not in the future"),
        (
            "POPPY_PHYSICAL_TRIAL_EXPIRES_AT",
            (START + timedelta(hours=8, minutes=6)).isoformat(),
            "eight-hour approval window",
        ),
    ],
)
def test_out_of_range_open_values_are_rejected(key: str, value: str, fragment: str) -> None:
    assert any(fragment in issue for issue in issues_for(**{key: value}))


def test_expiry_up_to_eight_hours_five_minutes_is_accepted() -> None:
    settings = open_settings(
        POPPY_PHYSICAL_TRIAL_EXPIRES_AT=(START + timedelta(hours=8, minutes=5)).isoformat()
    )
    assert settings.expires_at == START + timedelta(hours=8, minutes=5)
    assert open_settings(
        POPPY_PHYSICAL_TRIAL_EXPIRES_AT=(START + timedelta(hours=3)).isoformat()
    ).expires_at == START + timedelta(hours=3)


def test_agent_config_selects_open_mode_by_trial_mode() -> None:
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    config = unitree_config(
        enabled=True, trial={**OPEN_ENV, "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": expires}
    )
    assert isinstance(config.physical_trial, OpenMotionSettings)
    assert config.physical_trial_issues == ()


def test_preset_mapping_is_the_documented_sdk_allow_list() -> None:
    assert dict(PRESET_SDK_METHODS) == {
        "HELLO": "Hello",
        "STRETCH": "Stretch",
        "HEART": "Heart",
        "DANCE1": "Dance1",
    }


# --- SDK mapping ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "vx"), [(MoveDirection.FORWARD, 0.5), (MoveDirection.BACKWARD, -0.5)]
)
def test_move_streams_signed_vx_then_stop_move_three_times(
    direction: MoveDirection, vx: float
) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    settings = open_settings(POPPY_PHYSICAL_START_Y_M="1.0")
    result = run(build(clock, sport, settings=settings), move(0.5, direction))

    assert result.status is ExecutionStatus.COMPLETED
    assert len(sport.moves) == 20  # 0.5 m / 0.5 m/s = 1.0 s at 50 ms
    assert {args for _name, args in sport.moves} == {(vx, 0.0, 0.0)}
    assert sport.names() == ["Move", "StopMove", "StopMove", "StopMove"]


@pytest.mark.parametrize(("sign", "expected"), [(1, -1.0), (-1, 1.0)])
def test_turn_right_uses_configured_yaw_sign_at_45_degrees_per_second(
    sign: int, expected: float
) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    settings = open_settings(POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN=str(sign))
    result = run(build(clock, sport, settings=settings), turn(90))

    assert result.status is ExecutionStatus.COMPLETED
    assert len(sport.moves) == 40  # 90 / 45 = 2.0 s
    _, (move_vx, move_vy, vyaw) = sport.moves[0]
    assert (move_vx, move_vy) == (0.0, 0.0)
    assert vyaw == pytest.approx(expected * math.radians(45))
    assert sport.calls[-3:] == [("StopMove", ())] * 3


def test_sit_and_stand_use_settle_and_balance_stand() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), posture(Posture.SIT), wait(1), posture(Posture.STAND))

    assert result.status is ExecutionStatus.COMPLETED
    assert sport.names() == ["Sit", "RiseSit"]
    assert clock.waits == [3.0, 1.0, 3.0]


def test_stand_when_already_standing_uses_stand_up_and_balance_stand() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), posture(Posture.STAND), move(0.5))

    assert result.status is ExecutionStatus.COMPLETED
    assert sport.names()[:3] == ["StandUp", "BalanceStand", "Move"]
    assert clock.waits[0] == 3.0


def test_preset_calls_mapped_sdk_method_then_settle_and_balance_stand() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)
    for code, method in PRESET_SDK_METHODS.items():
        sport.calls.clear()
        clock.waits.clear()
        assert run(trial, preset(code)).status is ExecutionStatus.COMPLETED
        assert sport.names() == [method, "BalanceStand"]
        assert clock.waits == [5.0]


@pytest.mark.parametrize("code", ["FRONTFLIP", "FRONT_JUMP", "ROLL", "hello", ""])
def test_unlisted_preset_is_rejected_before_any_dispatch(code: str) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), preset(code))

    assert result.status is ExecutionStatus.FAILED
    assert sport.names() == []


def test_preset_outside_configured_subset_is_rejected() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    settings = open_settings(POPPY_PHYSICAL_ALLOWED_PRESETS="HELLO")
    result = run(build(clock, sport, settings=settings), preset("DANCE1"))

    assert result.status is ExecutionStatus.FAILED
    assert sport.names() == []


# --- per-Execution limits ------------------------------------------------------


@pytest.mark.parametrize(
    ("commands", "reason"),
    [
        ((move(0.9),) * 5, "leaves the arena"),
        ((move(3.1),), "per-command limit"),
        ((turn(361),), "per-command limit"),
        ((wait(10),) * 13, "total motion time"),
        ((posture(Posture.SIT), move(0.5)), "after SIT"),
        ((posture(Posture.SIT), turn(90)), "after SIT"),
        ((posture(Posture.SIT), preset("HELLO")), "after SIT"),
    ],
)
def test_limit_violations_fail_before_any_dispatch(commands: tuple, reason: str) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), *commands)

    assert result.status is ExecutionStatus.FAILED
    assert reason in (result.failure_reason or "")
    assert sport.names() == []


def program(*commands: tuple) -> HighLevelCommandProgram:
    return task(*commands).command_program


def arena_plan(*commands: tuple) -> float:
    guard = OpenMotionGuard(open_settings(), telemetry_fresh=lambda: True, now=lambda: START)
    return guard.plan(program(*commands), sitting=False).move_meters


LEFT = TurnDirection.LEFT
RIGHT = TurnDirection.RIGHT
BACKWARD = MoveDirection.BACKWARD


def test_screenshot_case_fails_on_third_move_after_left_turn() -> None:
    up = (move(0.6),) * 4
    assert arena_plan(*up, turn(90, LEFT), *(move(0.6),) * 2) == pytest.approx(3.6)
    with pytest.raises(OpenMotionGuardError, match="leaves the arena"):
        arena_plan(*up, turn(90, LEFT), *(move(0.6),) * 3)
    with pytest.raises(OpenMotionGuardError, match="leaves the arena"):
        arena_plan(*up, turn(90, LEFT), *(move(0.6),) * 5)


@pytest.mark.parametrize(
    ("commands", "allowed"),
    [
        ((move(3.0), move(0.2)), True),  # y = 3.6, on the allowed edge
        ((move(3.0), move(0.3)), False),  # y = 3.7
        ((turn(90, RIGHT), move(1.6)), True),  # x = 3.6
        ((turn(90, RIGHT), move(1.7)), False),  # x = 3.7
        ((turn(90, LEFT), move(1.6)), True),  # x = 0.4
        ((turn(90, LEFT), move(1.7)), False),  # x = 0.3
        ((move(0.1, BACKWARD),), False),  # the start is on the bottom edge
        ((move(1.0), move(1.0, BACKWARD)), True),
        ((turn(180), move(0.1)), False),  # facing the bottom wall
        ((turn(180), move(1.0, BACKWARD)), True),
    ],
)
def test_arena_boundary_and_direction(commands: tuple, allowed: bool) -> None:
    if allowed:
        arena_plan(*commands)
    else:
        with pytest.raises(OpenMotionGuardError, match="leaves the arena"):
            arena_plan(*commands)


def test_left_turn_is_counterclockwise_and_right_turn_is_clockwise() -> None:
    settings = open_settings(POPPY_PHYSICAL_START_X_M="0.4")
    guard = OpenMotionGuard(settings, telemetry_fresh=lambda: True, now=lambda: START)

    guard.plan(program(turn(90, RIGHT), move(3.0)), sitting=False)
    with pytest.raises(OpenMotionGuardError, match="leaves the arena"):
        guard.plan(program(turn(90, LEFT), move(0.1)), sitting=False)


def test_six_meter_arena_from_bottom_right_corner() -> None:
    settings = open_settings(
        POPPY_PHYSICAL_ARENA_WIDTH_M="6.0",
        POPPY_PHYSICAL_ARENA_DEPTH_M="6.0",
        POPPY_PHYSICAL_START_X_M="5.6",
    )
    guard = OpenMotionGuard(settings, telemetry_fresh=lambda: True, now=lambda: START)
    up = (move(0.6),) * 4

    guard.plan(program(*up, turn(90, LEFT), *(move(0.6),) * 5), sitting=False)
    with pytest.raises(OpenMotionGuardError, match="leaves the arena"):
        guard.plan(program(turn(90, RIGHT), move(0.5)), sitting=False)
    with pytest.raises(OpenMotionGuardError, match="leaves the arena"):
        guard.plan(program(move(0.5, BACKWARD)), sitting=False)


def test_total_distance_over_four_meters_is_allowed_inside_the_arena() -> None:
    assert arena_plan(*(move(1.5), move(1.5, BACKWARD)) * 3) == pytest.approx(9.0)


def test_disallowed_command_type_is_rejected() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    settings = open_settings(POPPY_PHYSICAL_ALLOWED_COMMANDS="TURN")
    result = run(build(clock, sport, settings=settings), move(0.5))

    assert result.status is ExecutionStatus.FAILED
    assert sport.names() == []


def test_edge_of_arena_and_stand_after_sit_are_allowed() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)

    assert run(trial, move(3.0), move(0.2)).status is ExecutionStatus.COMPLETED
    sport.calls.clear()
    result = run(trial, posture(Posture.SIT), posture(Posture.STAND), move(0.5), STOP)
    assert result.status is ExecutionStatus.COMPLETED
    assert sport.names()[:3] == ["Sit", "RiseSit", "Move"]


def test_sit_persists_across_executions_until_stand() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)

    assert run(trial, posture(Posture.SIT)).status is ExecutionStatus.COMPLETED
    blocked = run(trial, move(0.5))
    assert blocked.status is ExecutionStatus.FAILED
    assert "after SIT" in (blocked.failure_reason or "")
    sport.calls.clear()
    assert run(trial, posture(Posture.STAND), move(0.5)).status is ExecutionStatus.COMPLETED
    assert sport.names()[:2] == ["RiseSit", "Move"]


def test_executions_are_unlimited_and_budget_resets_each_execution() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)
    for _ in range(6):
        assert run(trial, move(1.0), move(1.0), move(1.0)).status is ExecutionStatus.COMPLETED
    assert trial.guard.snapshot()["executionsAdmitted"] == 6
    assert trial.guard.available() is True


def test_mission_programs_pass() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)
    patrol = (move(0.5), turn(90)) * 4
    missions = [
        (turn(90), STOP),  # look behind
        (move(0.5), STOP),  # delivery
        (posture(Posture.SIT), wait(1), posture(Posture.STAND), move(0.5), STOP),
        patrol,  # square patrol, repeat 4 expanded by the Server
        (preset("HELLO"), turn(180, TurnDirection.LEFT), move(1.0, MoveDirection.BACKWARD)),
        (preset("DANCE1"), preset("HEART"), preset("STRETCH")),
    ]
    for commands in missions:
        assert run(trial, *commands).status is ExecutionStatus.COMPLETED


def test_stop_ends_the_program_before_later_commands() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), STOP, turn(90))

    assert result.status is ExecutionStatus.COMPLETED
    assert sport.names() == ["Move", "StopMove", "StopMove", "StopMove"]


# --- failures, cancellation and expiry -----------------------------------------


def test_unknown_outcome_fails_only_that_execution_without_lock() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, move_error_at=3)
    trial = build(clock, sport)

    failed = run(trial, move(0.5))
    assert failed.status is ExecutionStatus.FAILED
    assert [name for name, _ in sport.calls[-3:]] == ["StopMove"] * 3
    assert trial.guard.snapshot()["lastFailure"] is not None
    assert trial.guard.available() is True

    sport.move_error_at = None
    assert run(trial, move(0.5)).status is ExecutionStatus.COMPLETED


def test_cancellation_during_wait_cancels_without_further_commands() -> None:
    clock = FakeClock(cancel_after_waits=1)
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), wait(5), move(0.5))

    assert result.status is ExecutionStatus.CANCELLED
    assert sport.names() == []


def test_stale_telemetry_rejects_physical_programs() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport, telemetry_fresh=False), move(0.5))

    assert result.status is ExecutionStatus.FAILED
    assert sport.names() == []


def test_expired_approval_blocks_every_execution() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)
    clock.wall = EXPIRES

    result = run(trial, move(0.5))
    assert result.status is ExecutionStatus.FAILED
    assert "expired" in (result.failure_reason or "")
    assert trial.guard.available() is False
    assert trial.guard.snapshot()["state"] == "EXPIRED"
    assert sport.names() == []


def test_guard_rejects_concurrent_admission() -> None:
    guard = OpenMotionGuard(open_settings(), telemetry_fresh=lambda: True, now=lambda: START)
    program = task(move(0.5)).command_program
    guard.admit(program)
    with pytest.raises(OpenMotionGuardError, match="already in progress"):
        guard.admit(program)
    guard.release()
    guard.admit(program)


# --- main wiring ---------------------------------------------------------------


class FakeAdapter:
    def __init__(self) -> None:
        self.fresh = True
        self.readiness = None

    def telemetry_is_fresh(self) -> bool:
        return self.fresh

    def set_command_readiness(self, readiness) -> None:
        self.readiness = readiness


class FakeRuntime:
    def __init__(self) -> None:
        self.active_execution_id: UUID | None = None
        self.physical_status = None

    def set_physical_execution_status(self, provider) -> None:
        self.physical_status = provider


def unitree_config(*, enabled: bool, trial: dict[str, str]) -> AgentConfig:
    return AgentConfig.from_environment(
        {
            "ROBOT_MODE": "unitree",
            "POPPY_ROBOT_ID": str(ROBOT_ID),
            "POPPY_ENABLE_PHYSICAL_EXECUTION": "true" if enabled else "false",
            "UNITREE_NETWORK_INTERFACE": "test-nic",
            "POPPY_ROBOT_MODEL": "GO2",
            "POPPY_ROBOT_EDITION": "EDU",
            "POPPY_ROBOT_FIRMWARE_VERSION": "fw",
            "UNITREE_SDK_VERSION": "sdk",
            "POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS": "5",
            **trial,
        }
    )


def test_main_wires_open_mode_ready_and_expiry(monkeypatch) -> None:
    clock = FakeClock()
    guard = OpenMotionGuard(open_settings(), telemetry_fresh=lambda: True, now=clock.wall_now)
    sentinel = object()
    monkeypatch.setattr(
        main_module,
        "create_open_motion_executor",
        lambda **_kwargs: OpenMotionExecution(sentinel, guard),  # type: ignore[arg-type]
    )

    def forbidden(**_kwargs: object) -> object:
        raise AssertionError("TURN-only trial executor must not be created")

    monkeypatch.setattr(main_module, "create_controlled_trial_executor", forbidden)
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    config = unitree_config(
        enabled=True, trial={**OPEN_ENV, "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": expires}
    )
    adapter, runtime = FakeAdapter(), FakeRuntime()

    executor = main_module._create_physical_trial_executor(
        config,
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert executor is sentinel
    assert adapter.readiness() is True
    status = runtime.physical_status()
    assert status["state"] == "READY"
    assert status["mode"] == "controlled_motion_open"
    assert status["allowedPresets"] == ["DANCE1", "HEART", "HELLO", "STRETCH"]

    clock.wall = EXPIRES
    assert adapter.readiness() is False
    assert runtime.physical_status()["state"] == "BLOCKED"
    assert runtime.physical_status()["reasons"] == ["TRIAL_EXPIRED"]


def test_main_open_mode_with_invalid_config_stays_heartbeat_only() -> None:
    config = unitree_config(
        enabled=True,
        trial={**OPEN_ENV, "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": "2020-01-01T00:00+09:00"},
    )
    adapter, runtime = FakeAdapter(), FakeRuntime()

    executor = main_module._create_physical_trial_executor(
        config,
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert executor is None
    status = runtime.physical_status()
    assert status["state"] == "BLOCKED"
    assert "POPPY_PHYSICAL_TRIAL_EXPIRES_AT is not in the future" in status["configIssues"]
