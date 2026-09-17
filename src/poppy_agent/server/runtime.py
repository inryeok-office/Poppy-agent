"""Agent lifecycle integration for register and heartbeat transport."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from inspect import signature
from threading import Event
from time import monotonic
from typing import cast
from uuid import UUID

from poppy_agent.agent import Agent, AgentSnapshot
from poppy_agent.command import CommandProtocolParseError, HighLevelCommandProtocolParser
from poppy_agent.execution import (
    ExecutionCancellationToken,
    ExecutionExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTask,
    UnsupportedExecutionProtocolError,
)
from poppy_agent.observability import (
    AGENT_REGISTERED,
    AGENT_STARTING,
    EXECUTION_ASSIGNED,
    EXECUTION_CANCELLATION_DETECTED,
    EXECUTION_CANCELLATION_REQUESTED,
    EXECUTION_CANCELLED,
    EXECUTION_COMPLETED,
    EXECUTION_FAILED,
    EXECUTION_RECOVERY_CHECKED,
    EXECUTION_RECOVERY_COMPLETED,
    EXECUTION_RECOVERY_DETECTED,
    EXECUTION_RECOVERY_FAILED,
    EXECUTION_RECOVERY_NO_ACTIVE,
    EXECUTION_RECOVERY_STARTED,
    EXECUTION_STARTED,
    RUNTIME_READY,
    RUNTIME_STOPPED,
    RUNTIME_STOPPING,
    STARTUP_FAILURE,
    log_event,
    safe_exception_type,
)
from poppy_agent.server.client import ServerApiError, ServerClient
from poppy_agent.server.config import ServerConfig
from poppy_agent.server.models import (
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HeartbeatRobotRequest,
    RobotRegistrationRequest,
    ServerExecutionDelivery,
    ServerExecutionRecoveryResponse,
    ServerExecutionReportStatus,
)

logger = logging.getLogger(__name__)


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
        log_event(logger, logging.INFO, AGENT_STARTING)
        snapshot = self.agent.start()
        try:
            response = self.server.register_agent(self._registration_request(snapshot))
        except Exception as exc:
            log_event(logger, logging.ERROR, STARTUP_FAILURE, error_type=safe_exception_type(exc))
            self.agent.shutdown()
            raise
        self.agent_id = response.agent_id
        log_event(
            logger,
            logging.INFO,
            AGENT_REGISTERED,
            agent_id=response.agent_id,
            robot_id=snapshot.identity.robot_id,
        )
        try:
            self.recover_interrupted_execution()
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                STARTUP_FAILURE,
                agent_id=response.agent_id,
                error_type=safe_exception_type(exc),
            )
            self.agent_id = None
            self.agent.shutdown()
            raise
        log_event(logger, logging.INFO, RUNTIME_READY, agent_id=response.agent_id)
        return response

    def recover_interrupted_execution(self) -> ServerExecutionRecoveryResponse | None:
        """Reconcile Server-owned active work before any new polling begins."""
        if self.agent_id is None:
            raise AgentServerRuntimeError("Agent must be registered before recovery")
        log_event(
            logger,
            logging.INFO,
            EXECUTION_RECOVERY_CHECKED,
            agent_id=self.agent_id,
        )
        discover = getattr(self.server, "discover_active_execution", None)
        recover = getattr(self.server, "recover_active_execution", None)
        if not callable(discover) and not callable(recover):
            log_event(logger, logging.INFO, EXECUTION_RECOVERY_NO_ACTIVE, agent_id=self.agent_id)
            return None
        if not callable(discover) or not callable(recover):
            raise AgentServerRuntimeError("Server recovery contract is incomplete")
        robot_id = _robot_uuid(self.agent.read_state())
        active = discover(self.agent_id, robot_id)
        if active is None:
            log_event(
                logger,
                logging.INFO,
                EXECUTION_RECOVERY_NO_ACTIVE,
                agent_id=self.agent_id,
                robot_id=robot_id,
            )
            return None
        log_event(
            logger,
            logging.WARNING,
            EXECUTION_RECOVERY_DETECTED,
            agent_id=self.agent_id,
            robot_id=robot_id,
            execution_id=active.execution_id,
            execution_status=active.status.value,
        )
        log_event(
            logger,
            logging.INFO,
            EXECUTION_RECOVERY_STARTED,
            agent_id=self.agent_id,
            robot_id=robot_id,
            execution_id=active.execution_id,
        )
        try:
            response = cast(ServerExecutionRecoveryResponse, recover(self.agent_id, robot_id))
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                EXECUTION_RECOVERY_FAILED,
                agent_id=self.agent_id,
                robot_id=robot_id,
                execution_id=active.execution_id,
                error_type=safe_exception_type(exc),
            )
            raise
        log_event(
            logger,
            logging.INFO,
            EXECUTION_RECOVERY_COMPLETED,
            agent_id=self.agent_id,
            robot_id=robot_id,
            execution_id=response.execution_id,
            execution_status=response.status.value if response.status is not None else None,
            recovery_action=response.action.value,
        )
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
        task = self._poll_and_mark_running()
        if task is None:
            return None
        try:
            result = self._execute_with_cancellation(executor, task)
        except Exception:
            self._report_failed_best_effort(task)
            raise
        return self._finish_execution(task, result)

    def run_heartbeat_loop(self, stop_event: Event) -> None:
        """Send heartbeats until stopped; transport failures propagate to the caller."""
        while not stop_event.is_set():
            self.heartbeat_once()
            if stop_event.wait(self.config.heartbeat_interval_seconds):
                return

    def run_loop(self, stop_event: Event, executor: ExecutionExecutor) -> None:
        """Run heartbeat and polling schedules while execution runs in one worker."""
        next_heartbeat = monotonic()
        next_execution_poll = next_heartbeat
        future: Future[ExecutionResult] | None = None
        task: ExecutionTask | None = None
        cancellation_token: ExecutionCancellationToken | None = None
        next_cancellation_check = next_heartbeat
        cancellation_monitor_error: Exception | None = None
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="poppy-execution")
        try:
            while not stop_event.is_set():
                now = monotonic()
                if (
                    future is not None
                    and task is not None
                    and cancellation_token is not None
                    and now >= next_cancellation_check
                ):
                    try:
                        self._poll_cancellation(task, cancellation_token)
                    except Exception as exc:
                        cancellation_monitor_error = exc
                        cancellation_token.cancel("execution cancellation status unavailable")
                    next_cancellation_check += max(0.1, self.config.execution_poll_interval_seconds)
                if now >= next_heartbeat:
                    self.heartbeat_once()
                    next_heartbeat += self.config.heartbeat_interval_seconds
                if future is None and now >= next_execution_poll:
                    task = self._poll_and_mark_running()
                    next_execution_poll += self.config.execution_poll_interval_seconds
                    if task is not None:
                        cancellation_token = ExecutionCancellationToken()
                        future = worker.submit(
                            _execute_with_optional_cancellation,
                            executor,
                            task,
                            cancellation_token,
                        )

                if future is not None and future.done():
                    assert task is not None
                    try:
                        result = future.result()
                    except Exception:
                        self._report_failed_best_effort(task)
                        raise
                    if cancellation_monitor_error is not None:
                        self._report_failed_best_effort(task)
                        raise AgentServerRuntimeError(
                            "execution cancellation status could not be verified"
                        ) from cancellation_monitor_error
                    self._finish_execution(task, result)
                    future = None
                    task = None
                    cancellation_token = None
                    cancellation_monitor_error = None

                if future is not None:
                    wait_seconds = min(0.1, max(0.0, next_heartbeat - monotonic()))
                else:
                    wait_seconds = min(
                        max(0.0, next_heartbeat - monotonic()),
                        max(0.0, next_execution_poll - monotonic()),
                    )
                if stop_event.wait(wait_seconds):
                    return
        finally:
            if future is not None and not future.done():
                if cancellation_token is not None:
                    cancellation_token.cancel("runtime stopping")
                future.cancel()
            worker.shutdown(wait=False, cancel_futures=True)

    def _poll_and_mark_running(self) -> ExecutionTask | None:
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
        try:
            command_program = HighLevelCommandProtocolParser().parse(delivery.command_payload)
            task = ExecutionTask(
                execution_id=delivery.execution_id,
                robot_id=delivery.robot_id,
                protocol_version=delivery.protocol_version,
                command_program=command_program,
            )
        except (CommandProtocolParseError, UnsupportedExecutionProtocolError):
            self._report_delivery_failed_best_effort(delivery)
            raise
        self.active_execution_id = task.execution_id
        log_event(
            logger,
            logging.INFO,
            EXECUTION_ASSIGNED,
            agent_id=self.agent_id,
            robot_id=task.robot_id,
            execution_id=task.execution_id,
            protocol_version=task.protocol_version,
        )
        try:
            if self._server_status_is_cancelled(task):
                self.active_execution_id = None
                return None
            self.server.report_execution_status(
                self.agent_id,
                task.execution_id,
                task.robot_id,
                ServerExecutionReportStatus.RUNNING,
            )
            log_event(
                logger,
                logging.INFO,
                EXECUTION_STARTED,
                agent_id=self.agent_id,
                robot_id=task.robot_id,
                execution_id=task.execution_id,
                execution_status=ServerExecutionReportStatus.RUNNING.value,
            )
        except Exception:
            self.active_execution_id = None
            if self._server_status_is_cancelled(task):
                return None
            raise
        return task

    def _finish_execution(self, task: ExecutionTask, result: ExecutionResult) -> ExecutionResult:
        agent_id = self._registered_agent_id()
        try:
            if result.execution_id != task.execution_id:
                raise AgentServerRuntimeError("Execution result identity does not match task")
            terminal_status = _terminal_report_status(result)
        except Exception:
            self._report_failed_best_effort(task)
            raise
        try:
            if result.status is not ExecutionStatus.CANCELLED and self._server_status_is_cancelled(
                task
            ):
                result = ExecutionResult(
                    task.execution_id,
                    ExecutionStatus.CANCELLED,
                )
                terminal_status = ServerExecutionReportStatus.CANCELLED
            self.server.report_execution_status(
                agent_id,
                task.execution_id,
                task.robot_id,
                terminal_status,
            )
        except ServerApiError:
            if result.status is not ExecutionStatus.CANCELLED and self._server_status_is_cancelled(
                task
            ):
                result = ExecutionResult(
                    task.execution_id,
                    ExecutionStatus.CANCELLED,
                )
                self.server.report_execution_status(
                    agent_id,
                    task.execution_id,
                    task.robot_id,
                    ServerExecutionReportStatus.CANCELLED,
                )
            else:
                raise
        self.active_execution_id = None
        event = {
            ExecutionStatus.COMPLETED: EXECUTION_COMPLETED,
            ExecutionStatus.FAILED: EXECUTION_FAILED,
            ExecutionStatus.CANCELLED: EXECUTION_CANCELLED,
        }[result.status]
        log_event(
            logger,
            logging.INFO if result.status is not ExecutionStatus.FAILED else logging.ERROR,
            event,
            agent_id=agent_id,
            robot_id=task.robot_id,
            execution_id=task.execution_id,
            execution_status=result.status.value,
        )
        return result

    def _execute_with_cancellation(
        self, executor: ExecutionExecutor, task: ExecutionTask
    ) -> ExecutionResult:
        token = ExecutionCancellationToken()
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="poppy-execution-once")
        future = worker.submit(_execute_with_optional_cancellation, executor, task, token)
        cancellation_error: Exception | None = None
        try:
            next_check = monotonic()
            while not future.done():
                if monotonic() >= next_check:
                    try:
                        self._poll_cancellation(task, token)
                    except Exception as exc:
                        cancellation_error = exc
                        token.cancel("execution cancellation status unavailable")
                    next_check += max(0.1, self.config.execution_poll_interval_seconds)
                Event().wait(0.01)
            result = future.result()
            if cancellation_error is not None:
                raise AgentServerRuntimeError(
                    "execution cancellation status could not be verified"
                ) from cancellation_error
            return result
        finally:
            worker.shutdown(wait=True, cancel_futures=True)

    def _poll_cancellation(
        self, task: ExecutionTask, cancellation_token: ExecutionCancellationToken
    ) -> None:
        get_status = getattr(self.server, "get_execution_status", None)
        if not callable(get_status):
            return
        status = get_status(self._registered_agent_id(), task.execution_id, task.robot_id).status
        if status.value == ExecutionStatus.CANCELLED.value:
            log_event(
                logger,
                logging.INFO,
                EXECUTION_CANCELLATION_DETECTED,
                agent_id=self._registered_agent_id(),
                robot_id=task.robot_id,
                execution_id=task.execution_id,
                execution_status=status.value,
            )
            cancellation_token.cancel("server requested cancellation")
            log_event(
                logger,
                logging.INFO,
                EXECUTION_CANCELLATION_REQUESTED,
                agent_id=self._registered_agent_id(),
                robot_id=task.robot_id,
                execution_id=task.execution_id,
            )
            self.active_execution_id = None

    def _server_status_is_cancelled(self, task: ExecutionTask) -> bool:
        get_status = getattr(self.server, "get_execution_status", None)
        if not callable(get_status):
            return False
        status = get_status(self._registered_agent_id(), task.execution_id, task.robot_id).status
        status_value: object = getattr(status, "value", None)
        return status_value == ExecutionStatus.CANCELLED.value

    def _report_failed_best_effort(self, task: ExecutionTask) -> None:
        agent_id = self._registered_agent_id()
        try:
            self.server.report_execution_status(
                agent_id,
                task.execution_id,
                task.robot_id,
                ServerExecutionReportStatus.FAILED,
            )
        except Exception:
            return
        log_event(
            logger,
            logging.ERROR,
            EXECUTION_FAILED,
            agent_id=agent_id,
            robot_id=task.robot_id,
            execution_id=task.execution_id,
            execution_status=ServerExecutionReportStatus.FAILED.value,
        )
        self.active_execution_id = None

    def _report_delivery_failed_best_effort(self, delivery: ServerExecutionDelivery) -> None:
        agent_id = self._registered_agent_id()
        try:
            self.server.report_execution_status(
                agent_id,
                delivery.execution_id,
                delivery.robot_id,
                ServerExecutionReportStatus.FAILED,
            )
        except Exception:
            return
        log_event(
            logger,
            logging.ERROR,
            EXECUTION_FAILED,
            agent_id=agent_id,
            robot_id=delivery.robot_id,
            execution_id=delivery.execution_id,
            execution_status=ServerExecutionReportStatus.FAILED.value,
        )

    def _registered_agent_id(self) -> UUID:
        if self.agent_id is None:
            raise AgentServerRuntimeError("Agent must be registered before execution")
        return self.agent_id

    def shutdown(self) -> None:
        """Close server transport and stop the local Agent."""
        log_event(logger, logging.INFO, RUNTIME_STOPPING, agent_id=self.agent_id)
        try:
            self.server.close()
        finally:
            self.agent.shutdown()
            log_event(logger, logging.INFO, RUNTIME_STOPPED, agent_id=self.agent_id)

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
    if result.status is ExecutionStatus.CANCELLED:
        return ServerExecutionReportStatus.CANCELLED
    raise AgentServerRuntimeError("Execution result status is not supported")


def _execute_with_optional_cancellation(
    executor: ExecutionExecutor,
    task: ExecutionTask,
    cancellation_token: ExecutionCancellationToken,
) -> ExecutionResult:
    execute = executor.execute
    try:
        supports_cancellation = "cancellation_token" in signature(execute).parameters
    except (TypeError, ValueError):
        supports_cancellation = False
    if supports_cancellation:
        return execute(task, cancellation_token=cancellation_token)
    return execute(task)


def _operational_status(snapshot: AgentSnapshot) -> str:
    if snapshot.status.operational_status == "IDLE":
        return "READY"
    if snapshot.status.operational_status in {"READY", "UNAVAILABLE"}:
        return snapshot.status.operational_status
    raise AgentServerRuntimeError("Robot operational status is not supported by the server")
