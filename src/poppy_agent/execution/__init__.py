"""Transport-independent execution core."""

from poppy_agent.execution.executor import (
    CommandExecutionTarget,
    ExecutionExecutor,
    MockCommandEvent,
    MockCommandTarget,
    MockExecutionExecutor,
)
from poppy_agent.execution.models import (
    SUPPORTED_EXECUTION_PROTOCOL_VERSION,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTask,
    UnsupportedExecutionProtocolError,
)
from poppy_agent.execution.safety import (
    CommandSafetyPolicy,
    ExecutionSafetyValidator,
    SafetyValidationError,
)

__all__ = [
    "SUPPORTED_EXECUTION_PROTOCOL_VERSION",
    "CommandExecutionTarget",
    "CommandSafetyPolicy",
    "ExecutionSafetyValidator",
    "ExecutionExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionTask",
    "MockCommandEvent",
    "MockCommandTarget",
    "MockExecutionExecutor",
    "SafetyValidationError",
    "UnsupportedExecutionProtocolError",
]
