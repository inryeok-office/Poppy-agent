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
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatRobotRequest,
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
)

__all__ = [
    "AgentRegistrationRequest",
    "AgentRegistrationResponse",
    "AgentServerRuntime",
    "AgentServerRuntimeError",
    "RuntimeConnectivityState",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "HeartbeatRobotRequest",
    "RobotRegistrationRequest",
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
