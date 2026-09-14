from uuid import UUID

import pytest

from poppy_agent.execution import (
    ExecutionExecutor,
    ExecutionStatus,
    ExecutionTask,
    MockExecutionExecutor,
    UnsupportedExecutionProtocolError,
)

EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000001")
ROBOT_ID = UUID("00000000-0000-0000-0000-000000000002")


def task() -> ExecutionTask:
    return ExecutionTask(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        protocol_version=1,
    )


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
