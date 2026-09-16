from uuid import UUID

import pytest

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
from poppy_agent.execution import (
    CommandSafetyPolicy,
    ExecutionStatus,
    ExecutionTargetError,
    ExecutionTask,
    MockExecutionExecutor,
)
from poppy_agent.hardware import (
    FakeHardwareBackend,
    FakeHardwareBackendError,
    FakeHardwareEvent,
    HardwareCommandTarget,
)

EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000001")
ROBOT_ID = UUID("00000000-0000-0000-0000-000000000002")


def command(
    sequence: int,
    source_block_id: str,
    command_type: CommandType,
    parameters: object,
) -> HighLevelCommand:
    return HighLevelCommand(
        sequence=sequence,
        source_block_id=source_block_id,
        type=command_type,
        parameters=parameters,  # type: ignore[arg-type]
    )


def task(*commands: HighLevelCommand) -> ExecutionTask:
    return ExecutionTask(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        protocol_version=1,
        command_program=HighLevelCommandProgram(protocol_version=1, commands=commands),
    )


def hardware_target(
    *supported: CommandType,
    fail_at_sequence: int | None = None,
) -> tuple[FakeHardwareBackend, HardwareCommandTarget]:
    backend = FakeHardwareBackend(supported, fail_at_sequence=fail_at_sequence)
    target = HardwareCommandTarget(backend)
    target.initialize()
    return backend, target


def test_fake_backend_has_no_sdk_dependency_and_explicit_lifecycle() -> None:
    backend = FakeHardwareBackend({CommandType.WAIT})

    assert backend.initialized is False
    assert backend.events == []
    backend.initialize()
    assert backend.initialized is True
    backend.shutdown()
    assert backend.initialized is False


def test_fake_backend_initialization_failure_is_explicit() -> None:
    backend = FakeHardwareBackend(set(), fail_initialize=True)

    with pytest.raises(FakeHardwareBackendError, match="initialization failure"):
        backend.initialize()


def test_hardware_target_support_is_explicit_and_fail_closed() -> None:
    _backend, target = hardware_target(CommandType.WAIT, CommandType.STOP)

    assert target.supports(CommandType.WAIT) is True
    assert target.supports(CommandType.MOVE) is False
    assert target.supports(CommandType.STOP) is True


def test_hardware_boundary_preserves_typed_intents_and_order() -> None:
    backend, target = hardware_target(
        CommandType.WAIT,
        CommandType.MOVE,
        CommandType.TURN,
        CommandType.POSTURE,
        CommandType.STOP,
    )
    commands = task(
        command(0, "wait-block", CommandType.WAIT, WaitParameters(2.5)),
        command(
            1,
            "move-block",
            CommandType.MOVE,
            MoveParameters(MoveDirection.FORWARD, 1.25),
        ),
        command(2, "turn-block", CommandType.TURN, TurnParameters(TurnDirection.LEFT, 90.0)),
        command(3, "sit-block", CommandType.POSTURE, PostureParameters(Posture.SIT)),
        command(4, "stand-block", CommandType.POSTURE, PostureParameters(Posture.STAND)),
        command(5, "stop-block", CommandType.STOP, StopParameters()),
    )

    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(commands)

    assert result.execution_id == EXECUTION_ID
    assert result.status is ExecutionStatus.COMPLETED
    assert backend.events == [
        FakeHardwareEvent(item.sequence, item.source_block_id, item.type, item.parameters)
        for item in commands.command_program.commands
    ]
    assert backend.events[0].parameters == WaitParameters(2.5)
    assert backend.events[1].parameters == MoveParameters(MoveDirection.FORWARD, 1.25)
    assert backend.events[2].parameters == TurnParameters(TurnDirection.LEFT, 90.0)
    assert backend.events[3].parameters == PostureParameters(Posture.SIT)
    assert backend.events[4].parameters == PostureParameters(Posture.STAND)


def test_unsupported_command_is_preflighted_before_any_backend_dispatch() -> None:
    backend, target = hardware_target(CommandType.WAIT, CommandType.STOP)
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(
        task(
            command(0, "wait", CommandType.WAIT, WaitParameters(0.0)),
            command(
                1,
                "move",
                CommandType.MOVE,
                MoveParameters(MoveDirection.FORWARD, 1.0),
            ),
        )
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == "execution target does not support command type MOVE"
    assert backend.events == []


def test_stop_is_recorded_and_later_commands_are_not_sent_to_backend() -> None:
    backend, target = hardware_target(CommandType.STOP, CommandType.WAIT)
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(
        task(
            command(0, "stop", CommandType.STOP, StopParameters()),
            command(1, "after-stop", CommandType.WAIT, WaitParameters(999.0)),
        )
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert [event.sequence for event in backend.events] == [0]


def test_backend_failure_propagates_as_failed_without_later_dispatch() -> None:
    backend, target = hardware_target(
        CommandType.WAIT,
        CommandType.MOVE,
        CommandType.STOP,
        fail_at_sequence=1,
    )
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(
        task(
            command(0, "before", CommandType.WAIT, WaitParameters(0.0)),
            command(
                1,
                "failure",
                CommandType.MOVE,
                MoveParameters(MoveDirection.BACKWARD, 0.5),
            ),
            command(2, "after", CommandType.STOP, StopParameters()),
        )
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == (
        "execution target failed: configured fake hardware failure at sequence 1"
    )
    assert [event.sequence for event in backend.events] == [0]


def test_preset_requires_explicit_policy_for_hardware_like_target() -> None:
    backend, target = hardware_target(CommandType.PRESET)
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(task(command(0, "preset", CommandType.PRESET, PresetParameters("demo"))))

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == (
        "PRESET execution is disabled until an explicit allow-list is configured"
    )
    assert backend.events == []


def test_preset_allowlist_allows_only_fake_intent_recording() -> None:
    backend, target = hardware_target(CommandType.PRESET)
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(preset_allowlist=frozenset({"demo"})),
        bound_robot_id=ROBOT_ID,
    ).execute(task(command(0, "preset", CommandType.PRESET, PresetParameters("demo"))))

    assert result.status is ExecutionStatus.COMPLETED
    assert backend.events[0].parameters == PresetParameters("demo")


def test_hardware_target_wraps_backend_failure() -> None:
    backend = FakeHardwareBackend({CommandType.WAIT})
    target = HardwareCommandTarget(backend)

    with pytest.raises(ExecutionTargetError, match="not initialized"):
        target.dispatch(command(0, "wait", CommandType.WAIT, WaitParameters(0.0)))
