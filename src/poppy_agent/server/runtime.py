"""Agent lifecycle integration for register and heartbeat transport."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event
from time import monotonic
from uuid import UUID

from poppy_agent.agent import Agent, AgentSnapshot
from poppy_agent.execution import ExecutionExecutor, ExecutionResult, ExecutionStatus, ExecutionTask
from poppy_agent.server.client import ServerClient
from poppy_agent.server.config import ServerConfig
from poppy_agent.server.models import (
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatRobotRequest,
    RobotRegistrationRequest,
    ServerExecutionReportStatus,
)


class AgentServerRuntimeError(RuntimeError):
    """Raised when local Agent state cannot satisfy the server contract."""


class AgentServerRuntime:
    """Register an Agent and coordinate heartbeat and optional execution work."""

    def __init__(self, agent: Agent, server: ServerClient, config: ServerConfig) -> None:
        self.agent = agent
        self.server = server
        self.config = config
        self.agent_id: UUID | None = None
        self.active_execution_id: UUID | None = None

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
        request = HeartbeatRequest(
            sent_at=datetime.now(UTC),
            robots=(
                HeartbeatRobotRequest(
                    robot_id=robot_id,
                    connection_status=snapshot.status.connection_status,
                    operational_status=_operational_status(snapshot),
                    battery_percent=snapshot.status.battery_percent,
                    current_execution_id=self.active_execution_id,
                    current_execution_id_provided=self.active_execution_id is not None,
                ),
            ),
        )
        return self.server.send_heartbeat(self.agent_id, request)

    def execution_once(self, executor: ExecutionExecutor) -> ExecutionResult | None:
        """Poll, execute, and report one assigned execution without robot commands."""
        if self.agent_id is None:
            raise AgentServerRuntimeError("Agent must be registered before execution")
        if self.active_execution_id is not None:
            raise AgentServerRuntimeError("An execution is already active")
        snapshot = self.agent.read_state()
        robot_id = _robot_uuid(snapshot)
        delivery = self.server.fetch_next_execution(self.agent_id, robot_id)
        if delivery is None:
            return None
        if delivery.robot_id != robot_id:
            raise AgentServerRuntimeError("Execution delivery robot identity does not match Agent")
        if delivery.status != "ASSIGNED":
            raise AgentServerRuntimeError("Execution delivery status is not ASSIGNED")
        task = ExecutionTask(
            execution_id=delivery.execution_id,
            robot_id=delivery.robot_id,
            protocol_version=delivery.protocol_version,
        )
        self.active_execution_id = task.execution_id
        try:
            self.server.report_execution_status(
                self.agent_id,
                task.execution_id,
                task.robot_id,
                ServerExecutionReportStatus.RUNNING,
            )
        except Exception:
            self.active_execution_id = None
            raise

        try:
            result = executor.execute(task)
        except Exception:
            try:
                self.server.report_execution_status(
                    self.agent_id,
                    task.execution_id,
                    task.robot_id,
                    ServerExecutionReportStatus.FAILED,
                )
            except Exception:
                pass
            else:
                self.active_execution_id = None
            raise

        if result.execution_id != task.execution_id:
            raise AgentServerRuntimeError("Execution result identity does not match task")
        terminal_status = _terminal_report_status(result)
        self.server.report_execution_status(
            self.agent_id,
            task.execution_id,
            task.robot_id,
            terminal_status,
        )
        self.active_execution_id = None
        return result

    def run_heartbeat_loop(self, stop_event: Event) -> None:
        """Send heartbeats until stopped; transport failures propagate to the caller."""
        while not stop_event.is_set():
            self.heartbeat_once()
            if stop_event.wait(self.config.heartbeat_interval_seconds):
                return

    def run_loop(self, stop_event: Event, executor: ExecutionExecutor) -> None:
        """Run heartbeat and execution polling schedules in one stoppable loop."""
        next_heartbeat = monotonic()
        next_execution_poll = next_heartbeat
        while not stop_event.is_set():
            now = monotonic()
            if now >= next_heartbeat:
                self.heartbeat_once()
                next_heartbeat += self.config.heartbeat_interval_seconds
            if now >= next_execution_poll:
                self.execution_once(executor)
                next_execution_poll += self.config.execution_poll_interval_seconds
            wait_seconds = min(
                max(0.0, next_heartbeat - monotonic()),
                max(0.0, next_execution_poll - monotonic()),
            )
            if stop_event.wait(wait_seconds):
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


def _terminal_report_status(result: ExecutionResult) -> ServerExecutionReportStatus:
    if result.status is ExecutionStatus.COMPLETED:
        return ServerExecutionReportStatus.COMPLETED
    if result.status is ExecutionStatus.FAILED:
        return ServerExecutionReportStatus.FAILED
    raise AgentServerRuntimeError("Execution result status is not supported")


def _operational_status(snapshot: AgentSnapshot) -> str:
    if snapshot.status.operational_status == "IDLE":
        return "READY"
    if snapshot.status.operational_status in {"READY", "UNAVAILABLE"}:
        return snapshot.status.operational_status
    raise AgentServerRuntimeError("Robot operational status is not supported by the server")
