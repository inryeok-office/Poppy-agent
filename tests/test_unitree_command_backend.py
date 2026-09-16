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
    ExecutionTask,
    MockExecutionExecutor,
)
from poppy_agent.hardware import (
    FakeUnitreeCommandClient,
    HardwareCommandIntent,
    HardwareCommandTarget,
    UnitreeCommandBackend,
    UnitreeCommandBackendError,
    UnitreeCommandOperation,
)

EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000001")
ROBOT_ID = UUID("00000000-0000-0000-0000-000000000002")


def command(
    sequence: int,
    command_type: CommandType,
    parameters: object,
) -> HighLevelCommand:
    return HighLevelCommand(
        sequence=sequence,
        source_block_id=f"block-{sequence}",
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


def initialized_backend(
    *,
    fail_operation: UnitreeCommandOperation | None = None,
) -> tuple[FakeUnitreeCommandClient, UnitreeCommandBackend, HardwareCommandTarget]:
    client = FakeUnitreeCommandClient(fail_operation=fail_operation)
    backend = UnitreeCommandBackend(client)
    target = HardwareCommandTarget(backend)
    target.initialize()
    return client, backend, target


def test_fake_unitree_client_is_sdk_free_and_has_explicit_lifecycle() -> None:
    client = FakeUnitreeCommandClient()

    assert client.initialized is False
    assert client.calls == []
    client.initialize()
    assert client.initialized is True
    client.shutdown()
    assert client.initialized is False


def test_fake_unitree_client_initialization_failure_is_deterministic() -> None:
    client = FakeUnitreeCommandClient(fail_initialize=True)

    with pytest.raises(UnitreeCommandBackendError, match="initialization failure"):
        client.initialize()

    assert client.initialized is False
    assert client.calls == []


def test_unitree_backend_supports_only_direct_or_execution_level_cases() -> None:
    _client, backend, _target = initialized_backend()

    assert backend.supports(CommandType.WAIT) is True
    assert backend.supports(CommandType.POSTURE) is True
    assert backend.supports(CommandType.STOP) is True
    assert backend.supports(CommandType.MOVE) is False
    assert backend.supports(CommandType.TURN) is False
    assert backend.supports(CommandType.PRESET) is False


def test_posture_mapping_records_official_operation_shape_in_fake_client() -> None:
    client, _backend, target = initialized_backend()
    execution_task = task(
        command(0, CommandType.POSTURE, PostureParameters(Posture.SIT)),
        command(1, CommandType.POSTURE, PostureParameters(Posture.STAND)),
        command(2, CommandType.STOP, StopParameters()),
    )

    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(execution_task)

    assert result.execution_id == EXECUTION_ID
    assert result.status is ExecutionStatus.COMPLETED
    assert [call.operation for call in client.calls] == [
        UnitreeCommandOperation.SIT,
        UnitreeCommandOperation.STAND_UP,
    ]


def test_wait_and_program_stop_do_not_call_physical_client_operations() -> None:
    client, _backend, target = initialized_backend()
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(
        task(
            command(0, CommandType.WAIT, WaitParameters(1.0)),
            command(1, CommandType.STOP, StopParameters()),
            command(2, CommandType.POSTURE, PostureParameters(Posture.SIT)),
        )
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert client.calls == []


@pytest.mark.parametrize(
    ("command_type", "parameters"),
    [
        (CommandType.MOVE, MoveParameters(MoveDirection.FORWARD, 1.0)),
        (CommandType.TURN, TurnParameters(TurnDirection.LEFT, 90.0)),
    ],
)
def test_distance_and_angle_commands_fail_closed_without_semantic_conversion(
    command_type: CommandType,
    parameters: object,
) -> None:
    client, _backend, target = initialized_backend()
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(task(command(0, command_type, parameters)))

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == (
        f"execution target does not support command type {command_type.value}"
    )
    assert client.calls == []


def test_preset_is_rejected_before_unitree_mapping() -> None:
    client, _backend, target = initialized_backend()
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(task(command(0, CommandType.PRESET, PresetParameters("demo"))))

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == (
        "PRESET execution is disabled until an explicit allow-list is configured"
    )
    assert client.calls == []


def test_preflight_rejects_later_unsupported_command_before_posture_call() -> None:
    client, _backend, target = initialized_backend()
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(
        task(
            command(0, CommandType.POSTURE, PostureParameters(Posture.SIT)),
            command(
                1,
                CommandType.MOVE,
                MoveParameters(MoveDirection.BACKWARD, 0.5),
            ),
        )
    )

    assert result.status is ExecutionStatus.FAILED
    assert client.calls == []


def test_supports_failure_is_normalized_to_failed_result_before_dispatch() -> None:
    client = FakeUnitreeCommandClient()

    class UnavailableSupportBackend(UnitreeCommandBackend):
        def supports(self, _command_type: CommandType) -> bool:
            raise RuntimeError("capability lookup unavailable")

    backend = UnavailableSupportBackend(client)
    target = HardwareCommandTarget(backend)
    target.initialize()

    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(task(command(0, CommandType.POSTURE, PostureParameters(Posture.SIT))))

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == ("execution target support is unavailable for POSTURE")
    assert client.calls == []


def test_fake_client_failure_propagates_to_failed_execution_result() -> None:
    client, _backend, target = initialized_backend(
        fail_operation=UnitreeCommandOperation.STAND_UP,
    )
    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(
        task(
            command(0, CommandType.POSTURE, PostureParameters(Posture.SIT)),
            command(1, CommandType.POSTURE, PostureParameters(Posture.STAND)),
            command(2, CommandType.STOP, StopParameters()),
        )
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == (
        "execution target failed: configured fake Unitree client failure for StandUp"
    )
    assert [call.operation for call in client.calls] == [UnitreeCommandOperation.SIT]


def test_fake_client_negative_result_propagates_to_failed_execution_result() -> None:
    client = FakeUnitreeCommandClient(operation_result=False)
    backend = UnitreeCommandBackend(client)
    target = HardwareCommandTarget(backend)
    target.initialize()

    result = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=ROBOT_ID,
    ).execute(task(command(0, CommandType.POSTURE, PostureParameters(Posture.SIT))))

    assert result.status is ExecutionStatus.FAILED
    assert (
        result.failure_reason == "execution target failed: Unitree client reported failure for SIT"
    )
    assert [call.operation for call in client.calls] == [UnitreeCommandOperation.SIT]


def test_unitree_backend_requires_initialization_before_dispatch() -> None:
    client = FakeUnitreeCommandClient()
    backend = UnitreeCommandBackend(client)

    with pytest.raises(UnitreeCommandBackendError, match="not initialized"):
        backend.dispatch(
            HardwareCommandIntent(
                0,
                "block-0",
                CommandType.POSTURE,
                PostureParameters(Posture.SIT),
            )
        )
