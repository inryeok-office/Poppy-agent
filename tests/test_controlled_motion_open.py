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
    "POPPY_PHYSICAL_MAX_TOTAL_MOVE_M": "4.0",
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

    def __init__(
        self,
        clock: FakeClock,
        *,
        move_error_at: int | None = None,
        fail_codes: dict[str, int] | None = None,
    ) -> None:
        self.clock = clock
        self.move_error_at = move_error_at
        self.fail_codes = dict(fail_codes or {})
        self.calls: list[tuple[str, tuple[float, ...]]] = []
        self.timeouts: list[float] = []

    def SetTimeout(self, seconds: float) -> None:
        self.timeouts.append(seconds)

    def _record(self, name: str, *args: float) -> int:
        self.calls.append((name, args))
        return self.fail_codes.get(name, 0)

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
    assert settings.max_total_move_meters == 4.0
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
        ("POPPY_PHYSICAL_MAX_TOTAL_MOVE_M", "4.1", "approved limit of 4"),
        ("POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND", "4.5", "approved limit of 4"),
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
    result = run(build(clock, sport), move(0.5, direction))

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
        ((move(0.9),) * 5, "total MOVE distance"),
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


def test_disallowed_command_type_is_rejected() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    settings = open_settings(POPPY_PHYSICAL_ALLOWED_COMMANDS="TURN")
    result = run(build(clock, sport, settings=settings), move(0.5))

    assert result.status is ExecutionStatus.FAILED
    assert sport.names() == []


def test_exactly_four_meters_and_stand_after_sit_are_allowed() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)

    assert run(trial, *((move(1.0),) * 4)).status is ExecutionStatus.COMPLETED
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
        assert run(trial, move(1.0), move(1.0), move(1.0), move(1.0)).status is (
            ExecutionStatus.COMPLETED
        )
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


# --- settle before PRESET/POSTURE after MOVE/TURN (HELLO was rejected 0.1 s after StopMove) ---


def test_settle_before_action_defaults_to_two_seconds_and_is_optional() -> None:
    assert open_settings().settle_before_action_seconds == 2.0
    assert (
        open_settings(POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S="0.5").settle_before_action_seconds
        == 0.5
    )
    assert (
        open_settings(POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S="0").settle_before_action_seconds == 0.0
    )
    assert "POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S" not in OPEN_MOTION_ENVIRONMENT_KEYS


@pytest.mark.parametrize("value", ["abc", "-1", "nan", "inf", "16"])
def test_invalid_settle_before_action_blocks_with_a_reason(value: str) -> None:
    issues = issues_for(POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S=value)

    assert any("POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S" in issue for issue in issues)


def test_move_then_preset_waits_for_the_robot_to_stop_before_the_sdk_call() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), preset("HELLO"))

    assert result.status is ExecutionStatus.COMPLETED
    names = sport.names()
    assert names[0] == "Move"
    # BalanceStand first (base stance), then wait, then Hello, then the usual BalanceStand.
    assert names[-4:] == ["StopMove", "BalanceStand", "Hello", "BalanceStand"]
    assert clock.waits[-3:] == [pytest.approx(2.0), 2.0, 5.0]


def test_turn_then_posture_waits_before_the_posture_command() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), turn(90), posture(Posture.STAND))

    assert result.status is ExecutionStatus.COMPLETED
    assert pytest.approx(2.0) in clock.waits
    assert clock.waits[-2:] == [pytest.approx(2.0), 3.0]
    assert "BalanceStand" not in sport.names()[: sport.names().index("StandUp")]


def test_preset_without_a_preceding_motion_does_not_wait() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)

    assert run(build(clock, sport), preset("HELLO")).status is ExecutionStatus.COMPLETED
    assert clock.waits == [5.0]


def test_time_already_spent_waiting_counts_as_settled() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), wait(1.5), preset("HELLO"))

    assert result.status is ExecutionStatus.COMPLETED
    assert clock.waits[-4:] == [1.5, pytest.approx(0.5), 2.0, 5.0]


def test_a_long_enough_wait_after_the_motion_needs_no_extra_settle() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), wait(3), preset("HELLO"))

    assert result.status is ExecutionStatus.COMPLETED
    assert clock.waits[-3:] == [3.0, 2.0, 5.0]


def test_settle_happens_once_per_motion_not_before_every_action() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), preset("HELLO"), preset("HEART"))

    assert result.status is ExecutionStatus.COMPLETED
    assert clock.waits[-4:] == [pytest.approx(2.0), 2.0, 5.0, 5.0]
    # the pre-balance happens once per motion; Heart follows Hello's own BalanceStand.
    assert sport.names()[-5:] == ["BalanceStand", "Hello", "BalanceStand", "Heart", "BalanceStand"]


def test_settle_can_be_shortened_or_disabled_by_configuration() -> None:
    for value, expected_tail in (
        ("0.5", [pytest.approx(0.5), 2.0, 5.0]),
        ("0", [2.0, 5.0]),
    ):
        clock = FakeClock()
        sport = FakeSportClient(clock)
        trial = build(
            clock, sport, settings=open_settings(POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S=value)
        )

        assert run(trial, move(0.5), preset("HELLO")).status is ExecutionStatus.COMPLETED
        assert clock.waits[-len(expected_tail) :] == expected_tail
        if value == "0":
            # no stop wait: the wait before the last two is still a short move-stream wait
            assert clock.waits[-3] < 1.0


def test_cancellation_during_the_settle_wait_sends_no_preset() -> None:
    probe_clock = FakeClock()
    run(build(probe_clock, FakeSportClient(probe_clock)), move(0.5))
    waits_for_the_move = len(probe_clock.waits)

    clock = FakeClock(cancel_after_waits=waits_for_the_move + 1)
    sport = FakeSportClient(clock)
    result = run(build(clock, sport), move(0.5), preset("HELLO"))

    assert result.status is ExecutionStatus.CANCELLED
    assert sport.names()[0] == "Move"
    assert "Hello" not in sport.names()
    assert "BalanceStand" not in sport.names()


def test_the_settle_wait_is_not_counted_in_the_planned_motion_time_limit() -> None:
    clock = FakeClock()
    trial = build(clock, FakeSportClient(clock))
    program = task(move(1.0), preset("HELLO")).command_program

    summary = trial.guard.plan(program, sitting=False)

    # MOVE 1 m at 0.5 m/s = 2 s, plus the 5 s preset settle; the 2 s stop wait is idle time.
    assert summary.motion_seconds == pytest.approx(7.0)


def test_a_program_at_the_time_limit_is_still_admitted_with_the_settle_wait() -> None:
    clock = FakeClock()
    trial = build(clock, FakeSportClient(clock))
    # 5 s preset settle x 23 + 2 s move = 117 s planned: inside the 120 s limit.
    commands = [move(1.0)] + [preset("HELLO") for _ in range(23)]

    assert run(trial, *commands).status is ExecutionStatus.COMPLETED


# --- optional speed source: wait until the Robot is slow (0.3 s minimum, 3 s maximum) ---


class SpeedProbeHarness:
    """Drive only the backend's settle logic with a fake clock and a scripted speed source."""

    def __init__(self, speeds: list[float | None]) -> None:
        from typing import Any

        from poppy_agent.hardware.unitree import OpenMotionActions, UnitreeCommandBackend

        self.now = 10.0
        self.waits: list[float] = []
        self.speeds = list(speeds)
        self.probes = 0

        def waiter(seconds: float, _token: object) -> None:
            self.waits.append(seconds)
            self.now += seconds

        def probe() -> float | None:
            self.probes += 1
            return self.speeds.pop(0) if self.speeds else self.last

        self.last: float | None = speeds[-1] if speeds else None
        actions = OpenMotionActions(
            waiter=waiter,
            posture_settle_seconds=3.0,
            preset_settle_seconds=5.0,
            preset_methods={},
            guard=None,  # type: ignore[arg-type]
            clock=lambda: self.now,
            speed_probe=probe,
        )
        self.backend: Any = UnitreeCommandBackend(object(), open_actions=actions)  # type: ignore[arg-type]
        self.backend._last_motion_ended_at = self.now

    def settle(self) -> None:
        self.backend._settle_before_action("HELLO", None)


def test_speed_probe_waits_at_least_the_minimum_even_if_the_robot_already_looks_stopped() -> None:
    harness = SpeedProbeHarness([0.0])
    harness.settle()

    assert harness.waits == [pytest.approx(0.1)] * 3
    assert harness.now - 10.0 == pytest.approx(0.3)


def test_speed_probe_proceeds_as_soon_as_the_robot_is_slow_enough() -> None:
    # probed from 0.3 s on: unknown, unknown, 0.4, 0.2, then below the 0.05 m/s threshold
    harness = SpeedProbeHarness([None, None, 0.4, 0.2, 0.01])
    harness.settle()

    assert sum(harness.waits) == pytest.approx(0.7)
    assert harness.backend._last_motion_ended_at is None


def test_speed_probe_proceeds_with_a_warning_after_the_maximum_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = SpeedProbeHarness([0.4])
    with caplog.at_level("WARNING", logger="poppy_agent.hardware.unitree"):
        harness.settle()

    assert sum(harness.waits) == pytest.approx(3.0)
    warnings = [
        r for r in caplog.records if getattr(r, "poppy_event", "") == "execution_physical_settle"
    ]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert warnings[0].poppy_context["execution_status"] == "MAX_WAIT_EXCEEDED"  # type: ignore[attr-defined]
    assert harness.backend._last_motion_ended_at is None


# --- BalanceStand first after a motion, per-call logs, no lock after a failed PRESET ---


def sdk_call_logs(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [
        {"event": r.poppy_event, **r.poppy_context}  # type: ignore[attr-defined]
        for r in caplog.records
        if getattr(r, "poppy_event", "") == "execution_physical_sdk_call"
    ]


def test_balance_before_preset_defaults_and_validation() -> None:
    assert open_settings().balance_before_preset_settle_seconds == 2.0
    zero = open_settings(POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S="0")
    assert zero.balance_before_preset_settle_seconds == 0.0
    assert "POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S" not in OPEN_MOTION_ENVIRONMENT_KEYS
    for bad in ("abc", "-1", "16"):
        issues = issues_for(POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S=bad)
        assert any("POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S" in issue for issue in issues)


def test_turn_then_preset_also_takes_the_base_stance_first() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)

    assert run(build(clock, sport), turn(90), preset("HEART")).status is ExecutionStatus.COMPLETED
    assert sport.names()[-3:] == ["BalanceStand", "Heart", "BalanceStand"]


def test_preset_alone_keeps_the_original_sequence() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)

    assert run(build(clock, sport), preset("HELLO")).status is ExecutionStatus.COMPLETED
    assert sport.names() == ["Hello", "BalanceStand"]


def test_balance_before_preset_can_be_switched_off() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    settings = open_settings(POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S="0")

    assert (
        run(build(clock, sport, settings=settings), move(0.5), preset("HELLO")).status
        is ExecutionStatus.COMPLETED
    )
    assert sport.names()[-3:] == ["StopMove", "Hello", "BalanceStand"]
    assert clock.waits[-2:] == [pytest.approx(2.0), 5.0]


def test_failed_base_stance_sends_no_preset_and_does_not_lock_the_next_execution() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, fail_codes={"BalanceStand": 3203})
    trial = build(clock, sport)

    failed = run(trial, move(0.5), preset("HELLO"))
    assert failed.status is ExecutionStatus.FAILED
    assert "Hello" not in sport.names()

    sport.fail_codes.clear()
    sport.calls.clear()
    assert run(trial, move(0.5)).status is ExecutionStatus.COMPLETED
    assert run(trial, preset("HELLO")).status is ExecutionStatus.COMPLETED
    assert trial.guard.available() is True


def test_failure_after_the_preset_does_not_lock_the_next_execution() -> None:
    # 2026-11-11: Hello was accepted, BalanceStand failed 5 s later.
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)
    sport.fail_codes = {}
    assert run(trial, move(0.5), preset("HELLO")).status is ExecutionStatus.COMPLETED

    sport.fail_codes = {"BalanceStand": 3203}
    sport.calls.clear()
    failed = run(trial, preset("HELLO"))
    assert failed.status is ExecutionStatus.FAILED
    assert sport.names() == ["Hello", "BalanceStand"]

    sport.fail_codes = {}
    sport.calls.clear()
    assert run(trial, move(0.5), preset("HEART")).status is ExecutionStatus.COMPLETED
    assert trial.guard.available() is True


def test_each_sdk_call_is_logged_with_its_name_and_return_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, fail_codes={"BalanceStand": 3203})
    with caplog.at_level("INFO", logger="poppy_agent.hardware.unitree_sdk"):
        result = run(build(clock, sport), move(0.5), preset("HELLO"))

    assert result.status is ExecutionStatus.FAILED
    logs = sdk_call_logs(caplog)
    assert [log["sdk_operation"] for log in logs] == ["BalanceStand"]
    assert logs[0]["execution_status"] == "FAILED"
    assert logs[0]["sdk_result_code"] == 3203
    assert not any(log["sdk_operation"] in {"Move", "StopMove"} for log in logs)


def test_successful_sequence_logs_each_call_in_order(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    with caplog.at_level("INFO", logger="poppy_agent.hardware.unitree_sdk"):
        run(build(clock, sport), move(0.5), preset("HELLO"))

    logs = sdk_call_logs(caplog)
    assert [(log["sdk_operation"], log["execution_status"]) for log in logs] == [
        ("BalanceStand", "OK"),
        ("Hello", "OK"),
        ("BalanceStand", "OK"),
    ]


def test_preset_failure_holds_the_next_physical_command_for_ten_seconds() -> None:
    # 2026-11-11: Dance1 was reported failed (SDK_RC_3104) while the Robot kept dancing.
    clock = FakeClock()
    sport = FakeSportClient(clock, fail_codes={"Hello": 4201})
    trial = build(clock, sport)

    assert run(trial, preset("HELLO")).status is ExecutionStatus.FAILED
    sport.fail_codes.clear()
    sport.calls.clear()
    clock.waits.clear()

    assert run(trial, move(0.5)).status is ExecutionStatus.COMPLETED
    assert clock.waits[0] == pytest.approx(10.0)
    assert sport.names()[0] == "Move"

    clock.waits.clear()
    assert run(trial, move(0.5)).status is ExecutionStatus.COMPLETED
    assert 10.0 not in [round(w, 6) for w in clock.waits]


def test_time_already_passed_after_a_preset_failure_counts_toward_the_hold() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, fail_codes={"Hello": 4201})
    trial = build(clock, sport)

    assert run(trial, preset("HELLO")).status is ExecutionStatus.FAILED
    sport.fail_codes.clear()
    clock.advance(30.0)
    clock.waits.clear()

    assert run(trial, preset("HEART")).status is ExecutionStatus.COMPLETED
    assert clock.waits == [5.0]


def test_failed_base_stance_before_a_preset_also_holds_the_next_command() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, fail_codes={"BalanceStand": 3203})
    trial = build(clock, sport)

    assert run(trial, move(0.5), preset("HELLO")).status is ExecutionStatus.FAILED
    sport.fail_codes.clear()
    clock.waits.clear()
    assert run(trial, preset("HELLO")).status is ExecutionStatus.COMPLETED
    assert clock.waits[0] == pytest.approx(10.0)


def test_cancellation_during_the_failure_hold_sends_nothing() -> None:
    clock = FakeClock(cancel_after_waits=1)
    sport = FakeSportClient(clock, fail_codes={"Hello": 4201})
    trial = build(clock, sport)

    assert run(trial, preset("HELLO")).status is ExecutionStatus.FAILED
    sport.fail_codes.clear()
    sport.calls.clear()
    clock.cancel_after_waits = len(clock.waits) + 1

    result = trial.executor.execute(task(preset("HEART")), ExecutionCancellationToken())
    assert result.status is ExecutionStatus.CANCELLED
    assert sport.names() == []


def test_only_preset_calls_get_the_long_sdk_timeout_and_it_is_restored() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build(clock, sport)

    assert run(trial, preset("DANCE1")).status is ExecutionStatus.COMPLETED
    assert sport.timeouts == [60.0, 10.0]
    sport.timeouts.clear()
    assert run(trial, move(0.5)).status is ExecutionStatus.COMPLETED
    assert sport.timeouts == []


def test_long_sdk_timeout_is_restored_when_the_preset_fails() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, fail_codes={"Dance1": 4201})
    trial = build(clock, sport)

    assert run(trial, preset("DANCE1")).status is ExecutionStatus.FAILED
    assert sport.timeouts == [60.0, 10.0]
