"""Transport-independent execution core."""

from poppy_agent.execution.cancellation import (
    CancellationSleeper,
    ExecutionCancellationToken,
    ExecutionCancelledError,
    InterruptibleSleeper,
)
from poppy_agent.execution.capability_evidence import (
    COMMAND_CAPABILITY_CODES,
    CapabilityEvidenceCache,
    CapabilityEvidenceClient,
    CapabilityEvidenceFailure,
    CapabilityEvidencePolicy,
    CapabilityEvidenceSnapshot,
    required_capability_codes,
)
from poppy_agent.execution.executor import (
    CommandExecutionTarget,
    ExecutionExecutor,
    ExecutionTargetError,
    MockCommandEvent,
    MockCommandTarget,
    MockExecutionExecutor,
)
from poppy_agent.execution.models import (
    SUPPORTED_EXECUTION_PROTOCOL_VERSION,
    SUPPORTED_EXECUTION_PROTOCOL_VERSIONS,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTask,
    UnsupportedExecutionProtocolError,
)
from poppy_agent.execution.motion import (
    MotionExecutionStrategy,
    MotionPlan,
    MotionProfile,
    MotionRateUnit,
    MotionSleeper,
    MotionStrategyError,
    MotionUnit,
    RecordingSleeper,
)
from poppy_agent.execution.physical_safety import (
    PhysicalMotionPolicy,
    PhysicalMotionPolicyError,
)
from poppy_agent.execution.readiness import (
    PhysicalCommandClientKind,
    PhysicalExecutionBlockedError,
    PhysicalExecutionGate,
    PhysicalExecutionReadiness,
    PhysicalReadinessBlocker,
    PhysicalReadinessEvaluator,
    PhysicalReadinessEvidence,
    PhysicalReadinessStatus,
)
from poppy_agent.execution.safety import (
    CommandSafetyPolicy,
    ExecutionSafetyValidator,
    SafetyValidationError,
)

__all__ = [
    "SUPPORTED_EXECUTION_PROTOCOL_VERSION",
    "SUPPORTED_EXECUTION_PROTOCOL_VERSIONS",
    "CancellationSleeper",
    "CommandExecutionTarget",
    "CommandSafetyPolicy",
    "ExecutionSafetyValidator",
    "ExecutionExecutor",
    "ExecutionCancellationToken",
    "CapabilityEvidenceCache",
    "CapabilityEvidenceClient",
    "CapabilityEvidenceFailure",
    "CapabilityEvidencePolicy",
    "CapabilityEvidenceSnapshot",
    "COMMAND_CAPABILITY_CODES",
    "required_capability_codes",
    "ExecutionCancelledError",
    "ExecutionTargetError",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionTask",
    "MotionExecutionStrategy",
    "MotionPlan",
    "MotionProfile",
    "MotionRateUnit",
    "MotionSleeper",
    "MotionStrategyError",
    "MotionUnit",
    "MockCommandEvent",
    "MockCommandTarget",
    "MockExecutionExecutor",
    "InterruptibleSleeper",
    "SafetyValidationError",
    "UnsupportedExecutionProtocolError",
    "RecordingSleeper",
    "PhysicalExecutionBlockedError",
    "PhysicalMotionPolicy",
    "PhysicalMotionPolicyError",
    "PhysicalExecutionGate",
    "PhysicalExecutionReadiness",
    "PhysicalCommandClientKind",
    "PhysicalReadinessBlocker",
    "PhysicalReadinessEvidence",
    "PhysicalReadinessEvaluator",
    "PhysicalReadinessStatus",
]
