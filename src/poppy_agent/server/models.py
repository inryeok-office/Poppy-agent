"""Typed request and response models matching Poppy-Server develop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RobotRegistrationRequest:
    """Robot registration data required by the server binding contract."""

    robot_id: UUID
    model: str
    edition: str
    firmware_version: str
    capabilities: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "robotId": str(self.robot_id),
            "model": self.model,
            "edition": self.edition,
            "firmwareVersion": self.firmware_version,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True, slots=True)
class AgentRegistrationRequest:
    """Register request matching `AgentRegistrationRequest` on the server."""

    agent_name: str
    agent_version: str
    sdk_version: str
    platform: str
    robots: tuple[RobotRegistrationRequest, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "agentName": self.agent_name,
            "agentVersion": self.agent_version,
            "sdkVersion": self.sdk_version,
            "platform": self.platform,
            "robots": [robot.to_json() for robot in self.robots],
        }


@dataclass(frozen=True, slots=True)
class AgentRegistrationResponse:
    """Parsed register response data."""

    agent_id: UUID
    registered_at: datetime
    accepted_robot_ids: tuple[UUID, ...]
    agent_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class HeartbeatRobotRequest:
    """One robot state item in a server heartbeat request."""

    robot_id: UUID
    connection_status: str
    operational_status: str
    battery_percent: int | None
    current_execution_id: UUID | None = None
    current_execution_id_provided: bool = True

    def __post_init__(self) -> None:
        if self.connection_status not in {"ONLINE", "OFFLINE"}:
            raise ValueError("connection_status must be ONLINE or OFFLINE")
        if self.operational_status not in {"READY", "UNAVAILABLE"}:
            raise ValueError("operational_status must be READY or UNAVAILABLE")
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            raise ValueError("battery_percent must be between 0 and 100")

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "robotId": str(self.robot_id),
            "connectionStatus": self.connection_status,
            "operationalStatus": self.operational_status,
            "batteryPercent": self.battery_percent,
        }
        if self.current_execution_id_provided:
            result["currentExecutionId"] = (
                str(self.current_execution_id) if self.current_execution_id is not None else None
            )
        return result


@dataclass(frozen=True, slots=True)
class HeartbeatRequest:
    """Heartbeat request matching the server's `AgentHeartbeatRequest`."""

    sent_at: datetime
    robots: tuple[HeartbeatRobotRequest, ...]

    def to_json(self) -> dict[str, object]:
        sent_at = self.sent_at
        if sent_at.tzinfo is not None:
            sent_at = sent_at.astimezone(UTC).replace(tzinfo=None)
        return {
            "sentAt": sent_at.isoformat(),
            "robots": [robot.to_json() for robot in self.robots],
        }


@dataclass(frozen=True, slots=True)
class HeartbeatResponse:
    """Parsed heartbeat response data."""

    agent_id: UUID
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class ServerExecutionDelivery:
    """Execution delivery data returned by the server polling endpoint."""

    execution_id: UUID
    robot_id: UUID
    status: str
    protocol_version: int
    command_payload: str


class ServerExecutionReportStatus(StrEnum):
    """Execution statuses supported by the server status-report contract."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ServerExecutionLifecycleStatus(StrEnum):
    """All lifecycle states returned by the server status endpoint."""

    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ServerExecutionStatusResponse:
    """Validated status-report response data returned by the server."""

    execution_id: UUID
    robot_id: UUID
    status: ServerExecutionReportStatus


@dataclass(frozen=True, slots=True)
class ServerExecutionStateResponse:
    """Authoritative full lifecycle state returned by the server."""

    execution_id: UUID
    robot_id: UUID
    status: ServerExecutionLifecycleStatus
