"""Poppy-Server client and contract models."""

from poppy_agent.server.client import (
    ServerApiError,
    ServerClient,
    ServerClientError,
    ServerResponseError,
    ServerTransportError,
)
from poppy_agent.server.config import ServerConfig, ServerConfigurationError
from poppy_agent.server.models import (
    AgentCapabilityEvidenceResponse,
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    CapabilityEvidenceStatus,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatRobotRequest,
    RobotCapabilityEvidence,
    RobotRegistrationRequest,
    ServerActiveExecutionResponse,
    ServerExecutionLifecycleStatus,
    ServerExecutionRecoveryAction,
    ServerExecutionRecoveryResponse,
    ServerExecutionReportStatus,
    ServerExecutionStateResponse,
    ServerExecutionStatusResponse,
)
from poppy_agent.server.runtime import (
    AgentServerRuntime,
    AgentServerRuntimeError,
    RuntimeConnectivityState,
    RuntimeLifecycleState,
)

__all__ = [
    "AgentRegistrationRequest",
    "AgentRegistrationResponse",
    "AgentCapabilityEvidenceResponse",
    "CapabilityEvidenceStatus",
    "AgentServerRuntime",
    "AgentServerRuntimeError",
    "RuntimeConnectivityState",
    "RuntimeLifecycleState",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "HeartbeatRobotRequest",
    "RobotRegistrationRequest",
    "RobotCapabilityEvidence",
    "ServerApiError",
    "ServerClient",
    "ServerClientError",
    "ServerConfig",
    "ServerConfigurationError",
    "ServerExecutionReportStatus",
    "ServerExecutionLifecycleStatus",
    "ServerExecutionStateResponse",
    "ServerExecutionStatusResponse",
    "ServerActiveExecutionResponse",
    "ServerExecutionRecoveryAction",
    "ServerExecutionRecoveryResponse",
    "ServerResponseError",
    "ServerTransportError",
]
