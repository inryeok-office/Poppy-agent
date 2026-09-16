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
    ExecutionExecutor,
    ExecutionStatus,
    ExecutionTask,
    MockCommandEvent,
    MockExecutionExecutor,
    UnsupportedExecutionProtocolError,
)

EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000001")
ROBOT_ID = UUID("00000000-0000-0000-0000-000000000002")


def task(program: HighLevelCommandProgram | None = None) -> ExecutionTask:
    return ExecutionTask(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        protocol_version=1,
        command_program=program or HighLevelCommandProgram(protocol_version=1, commands=()),
    )


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


def program(*commands: HighLevelCommand) -> HighLevelCommandProgram:
    return HighLevelCommandProgram(protocol_version=1, commands=commands)


def test_task_accepts_supported_protocol_with_uuid_metadata() -> None:
    execution_task = task()

    assert execution_task.execution_id == EXECUTION_ID
    assert execution_task.robot_id == ROBOT_ID
    assert execution_task.protocol_version == 1


@pytest.mark.parametrize("protocol_version", [True, 1.0, "1", 2])
def test_task_rejects_unsupported_or_non_integer_protocol_version(
    protocol_version: object,
) -> None:
    with pytest.raises(UnsupportedExecutionProtocolError, match="unsupported execution protocol"):
        ExecutionTask(
            execution_id=EXECUTION_ID,
            robot_id=ROBOT_ID,
            protocol_version=protocol_version,  # type: ignore[arg-type]
            command_program=HighLevelCommandProgram(protocol_version=1, commands=()),
        )


def test_mock_executor_completes_task_without_robot_or_network_dependency() -> None:
    executor: ExecutionExecutor = MockExecutionExecutor()

    result = executor.execute(task())

    assert result.execution_id == EXECUTION_ID
    assert result.status is ExecutionStatus.COMPLETED
    assert result.failure_reason is None


def test_mock_executor_returns_configured_deterministic_failure() -> None:
    result = MockExecutionExecutor(fail_execution=True).execute(task())

    assert result.execution_id == EXECUTION_ID
    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == "configured mock execution failure"


def test_mock_executor_completes_empty_program_with_empty_trace() -> None:
    executor = MockExecutionExecutor()

    result = executor.execute(task())

    assert result.status is ExecutionStatus.COMPLETED
    assert executor.events == []


def test_mock_executor_traces_all_typed_commands_in_sequence_order() -> None:
    executor = MockExecutionExecutor()
    commands = program(
        command(0, "wait-block", CommandType.WAIT, WaitParameters(2.5)),
        command(
            1,
            "forward-block",
            CommandType.MOVE,
            MoveParameters(MoveDirection.FORWARD, 1.25),
        ),
        command(
            2,
            "backward-block",
            CommandType.MOVE,
            MoveParameters(MoveDirection.BACKWARD, 0.75),
        ),
        command(
            3,
            "left-block",
            CommandType.TURN,
            TurnParameters(TurnDirection.LEFT, 90.0),
        ),
        command(
            4,
            "right-block",
            CommandType.TURN,
            TurnParameters(TurnDirection.RIGHT, 45.0),
        ),
        command(
            5,
            "sit-block",
            CommandType.POSTURE,
            PostureParameters(Posture.SIT),
        ),
        command(
            6,
            "stand-block",
            CommandType.POSTURE,
            PostureParameters(Posture.STAND),
        ),
        command(7, "preset-block", CommandType.PRESET, PresetParameters("demo")),
    )

    result = executor.execute(task(commands))

    assert result.status is ExecutionStatus.COMPLETED
    assert executor.events == [
        MockCommandEvent(item.sequence, item.source_block_id, item.type, item.parameters)
        for item in commands.commands
    ]
    assert executor.events[0].parameters == WaitParameters(2.5)
    assert executor.events[1].parameters == MoveParameters(MoveDirection.FORWARD, 1.25)
    assert executor.events[2].parameters == MoveParameters(MoveDirection.BACKWARD, 0.75)
    assert executor.events[3].parameters == TurnParameters(TurnDirection.LEFT, 90.0)
    assert executor.events[4].parameters == TurnParameters(TurnDirection.RIGHT, 45.0)
    assert executor.events[5].parameters == PostureParameters(Posture.SIT)
    assert executor.events[6].parameters == PostureParameters(Posture.STAND)
    assert executor.events[7].parameters == PresetParameters("demo")


def test_mock_executor_traces_stop_and_does_not_execute_following_commands() -> None:
    executor = MockExecutionExecutor()
    commands = program(
        command(0, "stop-block", CommandType.STOP, StopParameters()),
        command(1, "after-stop", CommandType.WAIT, WaitParameters(999.0)),
    )

    result = executor.execute(task(commands))

    assert result.execution_id == EXECUTION_ID
    assert result.status is ExecutionStatus.COMPLETED
    assert [event.sequence for event in executor.events] == [0]
    assert executor.events[0].source_block_id == "stop-block"
    assert executor.events[0].type is CommandType.STOP
    assert isinstance(executor.events[0].parameters, StopParameters)


def test_mock_executor_fails_at_sequence_without_executing_it_or_following_commands() -> None:
    executor = MockExecutionExecutor(fail_at_sequence=1)
    commands = program(
        command(0, "before-failure", CommandType.WAIT, WaitParameters(0.0)),
        command(1, "failure", CommandType.PRESET, PresetParameters("never")),
        command(2, "after-failure", CommandType.STOP, StopParameters()),
    )

    result = executor.execute(task(commands))

    assert result.execution_id == EXECUTION_ID
    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason == "configured mock execution failure at sequence 1"
    assert [event.sequence for event in executor.events] == [0]


def test_configured_failure_does_not_dispatch_commands() -> None:
    executor = MockExecutionExecutor(fail_execution=True)

    result = executor.execute(
        task(program(command(0, "never", CommandType.STOP, StopParameters())))
    )

    assert result.status is ExecutionStatus.FAILED
    assert executor.events == []
