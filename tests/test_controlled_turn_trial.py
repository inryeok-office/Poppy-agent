"""Controlled TURN trial: configuration, guard, streaming and wiring with fakes only."""

from __future__ import annotations

import math
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
from poppy_agent.config import AgentConfig
from poppy_agent.config.physical_trial import (
    PHYSICAL_TRIAL_ENVIRONMENT_KEYS,
    PhysicalTrialSettings,
    load_physical_trial_settings,
)
from poppy_agent.execution import ExecutionCancellationToken, ExecutionStatus, ExecutionTask
from poppy_agent.execution.motion import MotionPlan, MotionRateUnit, MotionUnit
from poppy_agent.execution.readiness import (
    PhysicalCommandClientKind,
    PhysicalExecutionBlockedError,
    PhysicalExecutionGate,
    PhysicalReadinessBlocker,
    PhysicalReadinessEvidence,
)
from poppy_agent.execution.trial import (
    TrialGuard,
    TrialGuardError,
    TrialGuardState,
    controlled_trial_readiness_evidence,
)
from poppy_agent.hardware import ControlledTrialExecution, create_controlled_trial_executor
from poppy_agent.hardware.unitree_sdk import (
    Go2TurnRateMapper,
    MotionStreamTiming,
    UnitreeTurnRateMappingError,
)

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")
EXECUTION_ID = UUID("00000000-0000-0000-0000-0000000000e1")
SIX_DEG_RAD = math.radians(6.0)

TRIAL_ENV = {
    "POPPY_PHYSICAL_TRIAL_MODE": "controlled_turn_v1",
    "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S": "6",
    "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND": "6",
    "POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG": "360",
    "POPPY_PHYSICAL_MAX_TOTAL_SECONDS": "60",
    "POPPY_PHYSICAL_MAX_COMMANDS": "1",
    "POPPY_PHYSICAL_ALLOWED_COMMANDS": "TURN",
    "POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN": "+1",
    "POPPY_PHYSICAL_APPROVAL_REF": "test-approval-ref",
}


def trial_settings(**overrides: str) -> PhysicalTrialSettings:
    settings, issues = load_physical_trial_settings({**TRIAL_ENV, **overrides})
    assert issues == ()
    assert settings is not None
    return settings


class FakeClock:
    """Fake monotonic clock; waits advance it and may cancel after N waits."""

    def __init__(self, *, cancel_after_waits: int | None = None) -> None:
        self.now = 100.0
        self.waits = 0
        self.cancel_after_waits = cancel_after_waits

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def wait(self, seconds: float, token: ExecutionCancellationToken | None) -> bool:
        self.waits += 1
        self.now += seconds
        if token is None:
            return False
        if self.cancel_after_waits is not None and self.waits >= self.cancel_after_waits:
            token.cancel("test cancellation")
        return token.is_cancelled()


class FakeSportClient:
    """Inert SportClient double; nothing here reaches DDS or a Robot."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        move_error_at: int | None = None,
        slow_move_at: int | None = None,
        stop_move_result: object = 0,
    ) -> None:
        self.clock = clock
        self.move_error_at = move_error_at
        self.slow_move_at = slow_move_at
        self.stop_move_result = stop_move_result
        self.calls: list[tuple[str, tuple[float, ...], float]] = []

    def Init(self) -> None:
        self.calls.append(("Init", (), self.clock.now))

    def Move(self, vx: float, vy: float, vyaw: float) -> int:
        index = len(self.moves)
        self.calls.append(("Move", (vx, vy, vyaw), self.clock.now))
        if self.move_error_at == index:
            raise RuntimeError("simulated transport failure")
        if self.slow_move_at == index:
            self.clock.now += 0.6
        return 0

    def StopMove(self) -> object:
        self.calls.append(("StopMove", (), self.clock.now))
        return self.stop_move_result

    def Close(self) -> None:
        self.calls.append(("Close", (), self.clock.now))

    @property
    def moves(self) -> list[tuple[str, tuple[float, ...], float]]:
        return [call for call in self.calls if call[0] == "Move"]

    @property
    def stop_moves(self) -> list[tuple[str, tuple[float, ...], float]]:
        return [call for call in self.calls if call[0] == "StopMove"]


def build_trial(
    clock: FakeClock,
    sport: FakeSportClient,
    *,
    settings: PhysicalTrialSettings | None = None,
    telemetry_fresh: bool = True,
) -> ControlledTrialExecution:
    return create_controlled_trial_executor(
        robot_id=ROBOT_ID,
        physical_execution_enabled=True,
        trial_settings=settings or trial_settings(),
        telemetry_fresh=lambda: telemetry_fresh,
        sport_client_factory=lambda: sport,
        timing=MotionStreamTiming(monotonic=clock.monotonic, sleep=clock.sleep, wait=clock.wait),
    )


def command(index: int, command_type: CommandType, parameters: object) -> HighLevelCommand:
    return HighLevelCommand(index, f"block-{index}", command_type, parameters)  # type: ignore[arg-type]


def task(*commands: HighLevelCommand) -> ExecutionTask:
    return ExecutionTask(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        protocol_version=1,
        command_program=HighLevelCommandProgram(1, tuple(commands)),
    )


def turn_task(direction: TurnDirection = TurnDirection.LEFT, angle: float = 6.0) -> ExecutionTask:
    return task(command(0, CommandType.TURN, TurnParameters(direction, angle)))


def turn_plan(direction: TurnDirection, rate: float = 6.0) -> MotionPlan:
    return MotionPlan(
        sequence=0,
        source_block_id="turn",
        command_type=CommandType.TURN,
        direction=direction,
        magnitude=6.0,
        magnitude_unit=MotionUnit.DEGREES,
        rate=rate,
        rate_unit=MotionRateUnit.DEGREES_PER_SECOND,
        duration_seconds=6.0 / rate,
    )


# --- configuration -------------------------------------------------------------


def test_complete_trial_configuration_loads_exact_values() -> None:
    settings = trial_settings()

    assert settings == PhysicalTrialSettings(
        mode="controlled_turn_v1",
        turn_rate_degrees_per_second=6.0,
        max_turn_degrees_per_command=6.0,
        max_total_turn_degrees=360.0,
        max_total_seconds=60.0,
        max_commands=1,
        turn_left_yaw_sign=1,
        approval_ref="test-approval-ref",
    )
    assert settings.turn_rate_radians_per_second == pytest.approx(0.10471975512)


@pytest.mark.parametrize("missing", PHYSICAL_TRIAL_ENVIRONMENT_KEYS)
def test_each_missing_trial_key_blocks_without_default(missing: str) -> None:
    values = {key: value for key, value in TRIAL_ENV.items() if key != missing}

    settings, issues = load_physical_trial_settings(values)

    assert settings is None
    assert f"{missing} is required" in issues


@pytest.mark.parametrize(
    ("key", "value", "fragment"),
    [
        ("POPPY_PHYSICAL_TRIAL_MODE", "free_motion", "must be controlled_turn_v1"),
        ("POPPY_PHYSICAL_TURN_RATE_DEG_PER_S", "46", "0.8 rad/s"),
        ("POPPY_PHYSICAL_TURN_RATE_DEG_PER_S", "nan", "positive finite"),
        ("POPPY_PHYSICAL_TURN_RATE_DEG_PER_S", "-6", "positive finite"),
        ("POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND", "361", "exceeds POPPY_PHYSICAL_MAX_TOTAL"),
        ("POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG", "361", "administrator limit of 360"),
        ("POPPY_PHYSICAL_MAX_TOTAL_SECONDS", "61", "administrator limit of 60"),
        ("POPPY_PHYSICAL_MAX_TOTAL_SECONDS", "0.5", "exceed POPPY_PHYSICAL_MAX_TOTAL_SECONDS"),
        ("POPPY_PHYSICAL_MAX_COMMANDS", "0", "positive integer"),
        ("POPPY_PHYSICAL_MAX_COMMANDS", "1.5", "positive integer"),
        ("POPPY_PHYSICAL_ALLOWED_COMMANDS", "TURN,MOVE", "exactly TURN"),
        ("POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN", "0", "+1 or -1"),
        ("POPPY_PHYSICAL_APPROVAL_REF", "x" * 121, "at most 120"),
    ],
)
def test_out_of_range_trial_values_block(key: str, value: str, fragment: str) -> None:
    settings, issues = load_physical_trial_settings({**TRIAL_ENV, key: value})

    assert settings is None
    assert any(fragment in issue for issue in issues)


def test_agent_config_keeps_trial_issues_instead_of_raising() -> None:
    config = AgentConfig.from_environment(
        {
            "ROBOT_MODE": "mock",
            "POPPY_ROBOT_ID": "robot",
            "POPPY_ENABLE_PHYSICAL_EXECUTION": "true",
        }
    )

    assert config.physical_trial is None
    assert len(config.physical_trial_issues) == len(PHYSICAL_TRIAL_ENVIRONMENT_KEYS)


def test_agent_config_without_physical_or_trial_keys_has_no_trial() -> None:
    config = AgentConfig.from_environment({"ROBOT_MODE": "mock", "POPPY_ROBOT_ID": "robot"})

    assert config.physical_trial is None
    assert config.physical_trial_issues == ()


def test_agent_config_parses_trial_while_physical_is_disabled() -> None:
    config = AgentConfig.from_environment(
        {"ROBOT_MODE": "mock", "POPPY_ROBOT_ID": "robot", **TRIAL_ENV}
    )

    assert config.enable_physical_execution is False
    assert config.physical_trial == trial_settings()


# --- readiness evidence ------------------------------------------------------------


def test_default_evidence_never_satisfies_hardware_validation() -> None:
    readiness = PhysicalExecutionGate().evaluate(
        physical_execution_enabled=True, evidence=PhysicalReadinessEvidence()
    )

    assert PhysicalReadinessBlocker.HARDWARE_VALIDATION_NOT_COMPLETED in readiness.blocking_reasons


def test_trial_evidence_is_ready_only_with_real_client_and_settings() -> None:
    gate = PhysicalExecutionGate()
    real = controlled_trial_readiness_evidence(
        trial_settings(), command_client_kind=PhysicalCommandClientKind.REAL
    )
    fake = controlled_trial_readiness_evidence(
        trial_settings(), command_client_kind=PhysicalCommandClientKind.FAKE
    )

    assert gate.evaluate(physical_execution_enabled=True, evidence=real).ready is True
    assert real.hardware_validation_completed is False
    assert real.controlled_trial_budget_defined is True
    assert gate.evaluate(physical_execution_enabled=True, evidence=fake).blocking_reasons == (
        PhysicalReadinessBlocker.REAL_COMMAND_CLIENT_MISSING,
    )
    assert gate.evaluate(physical_execution_enabled=False, evidence=real).blocking_reasons == (
        PhysicalReadinessBlocker.PHYSICAL_EXECUTION_DISABLED,
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_trial_factory_without_settings_blocks_before_sdk_construction(enabled: bool) -> None:
    def forbidden() -> object:
        raise AssertionError("SDK client must not be constructed")

    with pytest.raises(PhysicalExecutionBlockedError):
        create_controlled_trial_executor(
            robot_id=ROBOT_ID,
            physical_execution_enabled=enabled,
            trial_settings=None if enabled else trial_settings(),
            telemetry_fresh=lambda: True,
            sport_client_factory=forbidden,
        )


# --- mapping and streaming -------------------------------------------------------


@pytest.mark.parametrize(
    ("sign", "direction", "expected"),
    [
        (1, TurnDirection.LEFT, SIX_DEG_RAD),
        (1, TurnDirection.RIGHT, -SIX_DEG_RAD),
        (-1, TurnDirection.LEFT, -SIX_DEG_RAD),
        (-1, TurnDirection.RIGHT, SIX_DEG_RAD),
    ],
)
def test_turn_mapper_applies_configured_left_yaw_sign(
    sign: int, direction: TurnDirection, expected: float
) -> None:
    command_ = Go2TurnRateMapper(sign)(turn_plan(direction))

    assert (command_.vx, command_.vy) == (0.0, 0.0)
    assert command_.vyaw == pytest.approx(expected)


def test_turn_mapper_rejects_rate_above_go2_limit() -> None:
    with pytest.raises(UnitreeTurnRateMappingError, match="0.8 rad/s"):
        Go2TurnRateMapper(1)(turn_plan(TurnDirection.LEFT, rate=46.0))


@pytest.mark.parametrize(
    ("direction", "sign", "expected_vyaw"),
    [(TurnDirection.LEFT, "+1", SIX_DEG_RAD), (TurnDirection.RIGHT, "+1", -SIX_DEG_RAD)],
)
def test_six_degree_turn_streams_move_then_stops_three_times(
    direction: TurnDirection, sign: str, expected_vyaw: float
) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(
        clock, sport, settings=trial_settings(POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN=sign)
    )
    start = clock.now

    result = trial.executor.execute(turn_task(direction))

    assert result.status is ExecutionStatus.COMPLETED
    assert len(sport.moves) == 20
    for _name, args, at in sport.moves:
        assert args[:2] == (0.0, 0.0)
        assert args[2] == pytest.approx(expected_vyaw)
        assert at - start < 1.0
    assert len(sport.stop_moves) == 3
    assert sport.stop_moves[0][2] - start == pytest.approx(1.0)
    assert sport.stop_moves[-1][2] - sport.stop_moves[0][2] == pytest.approx(0.1)
    assert trial.guard.snapshot().state is TrialGuardState.EXHAUSTED


def test_cancellation_during_streaming_stops_three_times() -> None:
    clock = FakeClock(cancel_after_waits=5)
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport)

    result = trial.executor.execute(turn_task(), cancellation_token=ExecutionCancellationToken())

    assert result.status is ExecutionStatus.CANCELLED
    assert len(sport.moves) == 5
    assert len(sport.stop_moves) == 3
    assert trial.guard.snapshot().state is TrialGuardState.EXHAUSTED


def test_cancellation_without_confirmed_stop_move_locks() -> None:
    clock = FakeClock(cancel_after_waits=5)
    sport = FakeSportClient(clock, stop_move_result=3104)
    trial = build_trial(clock, sport)

    result = trial.executor.execute(turn_task(), cancellation_token=ExecutionCancellationToken())

    assert result.status is ExecutionStatus.FAILED
    assert trial.guard.snapshot().state is TrialGuardState.LOCKED


@pytest.mark.parametrize(
    "sport_options",
    [
        {"move_error_at": 3},
        {"slow_move_at": 2},
        {"stop_move_result": 3104},
    ],
    ids=["move-exception", "move-blocked", "stop-move-unconfirmed"],
)
def test_unknown_outcome_fails_stops_and_locks(sport_options: dict[str, object]) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, **sport_options)  # type: ignore[arg-type]
    trial = build_trial(clock, sport, settings=trial_settings(POPPY_PHYSICAL_MAX_COMMANDS="2"))

    result = trial.executor.execute(turn_task())

    assert result.status is ExecutionStatus.FAILED
    assert len(sport.stop_moves) == 3
    snapshot = trial.guard.snapshot()
    assert snapshot.state is TrialGuardState.LOCKED
    moves_before = len(sport.moves)

    second = trial.executor.execute(turn_task())

    assert second.status is ExecutionStatus.FAILED
    assert "locked" in (second.failure_reason or "")
    assert len(sport.moves) == moves_before


# --- trial guard ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command_type", "parameters"),
    [
        (CommandType.MOVE, MoveParameters(MoveDirection.BACKWARD, 0.1)),
        (CommandType.POSTURE, PostureParameters(Posture.SIT)),
        (CommandType.PRESET, PresetParameters("hello")),
    ],
)
def test_non_turn_physical_commands_are_rejected_without_sdk_calls(
    command_type: CommandType, parameters: object
) -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport)

    result = trial.executor.execute(task(command(0, command_type, parameters)))

    assert result.status is ExecutionStatus.FAILED
    assert [call[0] for call in sport.calls] == ["Init"]
    assert trial.guard.snapshot().commands_used == 0


def test_seven_degree_turn_is_rejected() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport)

    result = trial.executor.execute(turn_task(angle=7.0))

    assert result.status is ExecutionStatus.FAILED
    assert sport.moves == []


def test_second_execution_is_rejected_after_budget_is_used() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport)

    assert trial.executor.execute(turn_task()).status is ExecutionStatus.COMPLETED
    second = trial.executor.execute(turn_task())

    assert second.status is ExecutionStatus.FAILED
    assert "budget" in (second.failure_reason or "")
    assert len(sport.moves) == 20


def test_two_turns_in_one_program_exceed_single_command_budget() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport)
    left = TurnParameters(TurnDirection.LEFT, 3.0)

    result = trial.executor.execute(
        task(command(0, CommandType.TURN, left), command(1, CommandType.TURN, left))
    )

    assert result.status is ExecutionStatus.FAILED
    assert sport.moves == []


def test_wait_and_program_stop_are_allowed_and_stop_is_not_stop_move() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport)

    result = trial.executor.execute(
        task(
            command(0, CommandType.WAIT, WaitParameters(0.0)),
            command(1, CommandType.TURN, TurnParameters(TurnDirection.LEFT, 6.0)),
            command(2, CommandType.STOP, StopParameters()),
        )
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert len(sport.stop_moves) == 3


def test_stale_telemetry_rejects_without_consuming_budget() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock)
    trial = build_trial(clock, sport, telemetry_fresh=False)

    result = trial.executor.execute(turn_task())

    assert result.status is ExecutionStatus.FAILED
    assert sport.moves == []
    assert trial.guard.snapshot().commands_used == 0


def test_guard_debits_before_dispatch_and_never_refunds() -> None:
    guard = TrialGuard(trial_settings(), telemetry_fresh=lambda: True)
    program = turn_task().command_program

    guard.admit(program)
    assert guard.snapshot().state is TrialGuardState.EXECUTING
    with pytest.raises(TrialGuardError, match="in progress"):
        guard.admit(program)
    guard.release()

    snapshot = guard.snapshot()
    assert snapshot.state is TrialGuardState.EXHAUSTED
    assert snapshot.commands_used == 1
    assert snapshot.turn_degrees_used == 6.0
    assert snapshot.motion_seconds_used == pytest.approx(1.0)


# --- Robot adapter and runtime wiring ---------------------------------------------


def test_adapter_reports_ready_only_with_fresh_telemetry_and_readiness(monkeypatch) -> None:
    from poppy_agent.robot import RobotIdentity, UnitreeGo2Adapter, UnitreeGo2Config

    clock = FakeClock()
    adapter = UnitreeGo2Adapter(
        UnitreeGo2Config(
            network_interface="test-nic",
            identity=RobotIdentity(str(ROBOT_ID), "GO2", "EDU", "fw", "sdk"),
            telemetry_stale_timeout_seconds=5.0,
        ),
        monotonic_clock=clock.monotonic,
    )
    monkeypatch.setattr(adapter, "_initialized", True)
    readiness = {"value": True}

    assert adapter.capabilities() == ("TELEMETRY", "COMMAND_TURN")
    assert adapter.status().operational_status == "UNAVAILABLE"

    adapter._handle_state(SimpleNamespace(bms_state=SimpleNamespace(soc=80)))
    assert adapter.telemetry_is_fresh() is True
    assert adapter.status().operational_status == "UNAVAILABLE"

    adapter.set_command_readiness(lambda: readiness["value"])
    assert adapter.status().operational_status == "READY"

    readiness["value"] = False
    assert adapter.status().operational_status == "UNAVAILABLE"

    readiness["value"] = True
    clock.now += 6.0
    assert adapter.status().operational_status == "UNAVAILABLE"

    adapter._handle_state(SimpleNamespace(bms_state=SimpleNamespace(soc=80)))

    def broken() -> bool:
        raise RuntimeError("readiness failure")

    adapter.set_command_readiness(broken)
    assert adapter.status().operational_status == "UNAVAILABLE"


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


def unitree_config(*, enabled: bool, trial: dict[str, str] | None = None) -> AgentConfig:
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
            **(trial or {}),
        }
    )


def test_physical_disabled_never_creates_sdk_client(monkeypatch) -> None:
    def forbidden(**_kwargs: object) -> object:
        raise AssertionError("trial executor must not be created")

    monkeypatch.setattr(main_module, "create_controlled_trial_executor", forbidden)
    adapter, runtime = FakeAdapter(), FakeRuntime()

    executor = main_module._create_physical_trial_executor(
        unitree_config(enabled=False, trial=TRIAL_ENV),
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert executor is None
    assert adapter.readiness is None
    assert runtime.physical_status() == {
        "enabled": False,
        "state": "BLOCKED",
        "reasons": ["PHYSICAL_EXECUTION_DISABLED"],
        "configIssues": [],
    }


def test_missing_trial_config_stays_alive_heartbeat_only() -> None:
    adapter, runtime = FakeAdapter(), FakeRuntime()

    executor = main_module._create_physical_trial_executor(
        unitree_config(enabled=True),
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert executor is None
    assert adapter.readiness is None
    status = runtime.physical_status()
    assert status["state"] == "BLOCKED"
    assert status["reasons"][0] == "TRIAL_CONFIGURATION_INVALID"
    assert "POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN is required" in status["configIssues"]


def test_sdk_initialization_failure_stays_alive_heartbeat_only(monkeypatch) -> None:
    def failing(**_kwargs: object) -> object:
        raise RuntimeError("simulated SDK init failure")

    monkeypatch.setattr(main_module, "create_controlled_trial_executor", failing)
    adapter, runtime = FakeAdapter(), FakeRuntime()

    executor = main_module._create_physical_trial_executor(
        unitree_config(enabled=True, trial=TRIAL_ENV),
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert executor is None
    assert runtime.physical_status()["reasons"] == [
        "SDK_COMMAND_CLIENT_INITIALIZATION_FAILED:RuntimeError"
    ]


def test_ready_condition_table(monkeypatch) -> None:
    guard = TrialGuard(trial_settings(), telemetry_fresh=lambda: True)
    sentinel_executor = object()
    monkeypatch.setattr(
        main_module,
        "create_controlled_trial_executor",
        lambda **_kwargs: ControlledTrialExecution(sentinel_executor, guard),  # type: ignore[arg-type]
    )
    adapter, runtime = FakeAdapter(), FakeRuntime()

    executor = main_module._create_physical_trial_executor(
        unitree_config(enabled=True, trial=TRIAL_ENV),
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert executor is sentinel_executor
    ready = adapter.readiness
    assert ready is not None
    assert ready() is True
    assert runtime.physical_status()["state"] == "READY"
    assert runtime.physical_status()["trial"]["approvalRef"] == "test-approval-ref"

    adapter.fresh = False
    assert runtime.physical_status()["state"] == "NOT_READY"
    adapter.fresh = True

    runtime.active_execution_id = EXECUTION_ID
    assert ready() is False
    runtime.active_execution_id = None

    guard.admit(turn_task().command_program)
    assert ready() is False
    guard.release()
    assert ready() is False
    assert runtime.physical_status()["trial"]["state"] == "EXHAUSTED"

    locked = TrialGuard(trial_settings(), telemetry_fresh=lambda: True)
    locked.lock("test")
    assert locked.available() is False
