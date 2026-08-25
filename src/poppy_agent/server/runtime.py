"""Agent lifecycle integration for register and heartbeat transport."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event
from uuid import UUID

from poppy_agent.agent import Agent, AgentSnapshot
from poppy_agent.server.client import ServerClient
from poppy_agent.server.config import ServerConfig
from poppy_agent.server.models import (
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatRobotRequest,
    RobotRegistrationRequest,
)


class AgentServerRuntimeError(RuntimeError):
    """Raised when local Agent state cannot satisfy the server contract."""


class AgentServerRuntime:
    """Register a running Agent and expose a bounded heartbeat loop."""

    def __init__(self, agent: Agent, server: ServerClient, config: ServerConfig) -> None:
        self.agent = agent
        self.server = server
        self.config = config
        self.agent_id: UUID | None = None

    def start(self) -> AgentRegistrationResponse:
        """Start the Robot adapter, register the Agent, and retain its ID in memory."""
        if self.agent_id is not None:
            raise AgentServerRuntimeError("Agent is already registered")
        snapshot = self.agent.start()
        try:
            response = self.server.register_agent(self._registration_request(snapshot))
        except Exception:
            self.agent.shutdown()
            raise
        self.agent_id = response.agent_id
        return response

    def heartbeat_once(self) -> HeartbeatResponse:
        """Read current Robot state and send one heartbeat."""
        if self.agent_id is None:
            raise AgentServerRuntimeError("Agent must be registered before heartbeat")
        snapshot = self.agent.read_state()
        robot_id = _robot_uuid(snapshot)
        current_execution_id = _optional_uuid(snapshot.status.current_execution_id)
        request = HeartbeatRequest(
            sent_at=datetime.now(UTC),
            robots=(
                HeartbeatRobotRequest(
                    robot_id=robot_id,
                    connection_status=snapshot.status.connection_status,
                    operational_status=_operational_status(snapshot),
                    battery_percent=snapshot.status.battery_percent,
                    current_execution_id=current_execution_id,
                ),
            ),
        )
        return self.server.send_heartbeat(self.agent_id, request)

    def run_heartbeat_loop(self, stop_event: Event) -> None:
        """Send heartbeats until stopped; transport failures propagate to the caller."""
        while not stop_event.is_set():
            self.heartbeat_once()
            if stop_event.wait(self.config.heartbeat_interval_seconds):
                return

    def shutdown(self) -> None:
        """Close server transport and stop the local Agent."""
        try:
            self.server.close()
        finally:
            self.agent.shutdown()

    def _registration_request(self, snapshot: AgentSnapshot) -> AgentRegistrationRequest:
        return AgentRegistrationRequest(
            agent_name=self.config.agent_name,
            agent_version=self.config.agent_version,
            sdk_version=self.config.sdk_version,
            platform=self.config.platform,
            robots=(
                RobotRegistrationRequest(
                    robot_id=_robot_uuid(snapshot),
                    model=snapshot.identity.model,
                    edition=snapshot.identity.edition,
                    firmware_version=snapshot.identity.firmware_version,
                    capabilities=snapshot.capabilities,
                ),
            ),
        )


def _robot_uuid(snapshot: AgentSnapshot) -> UUID:
    try:
        return UUID(snapshot.identity.robot_id)
    except ValueError as exc:
        raise AgentServerRuntimeError(
            "Robot identity must be a UUID for the Poppy-Server contract"
        ) from exc


def _optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise AgentServerRuntimeError("current execution identity must be a UUID") from exc


def _operational_status(snapshot: AgentSnapshot) -> str:
    if snapshot.status.operational_status == "IDLE":
        return "READY"
    if snapshot.status.operational_status in {"READY", "UNAVAILABLE"}:
        return snapshot.status.operational_status
    raise AgentServerRuntimeError("Robot operational status is not supported by the server")
