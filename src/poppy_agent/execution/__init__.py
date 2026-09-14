"""Transport-independent execution core."""

from poppy_agent.execution.executor import ExecutionExecutor, MockExecutionExecutor
from poppy_agent.execution.models import (
    SUPPORTED_EXECUTION_PROTOCOL_VERSION,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTask,
    UnsupportedExecutionProtocolError,
)

__all__ = [
    "SUPPORTED_EXECUTION_PROTOCOL_VERSION",
    "ExecutionExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionTask",
    "MockExecutionExecutor",
    "UnsupportedExecutionProtocolError",
]
