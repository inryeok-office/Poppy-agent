from dataclasses import replace
from datetime import datetime
from threading import Event, Thread
from time import monotonic, sleep
from uuid import UUID

import pytest

from poppy_agent.agent import create_agent
from poppy_agent.config import AgentConfig
from poppy_agent.execution import ExecutionResult, ExecutionStatus, ExecutionTask
from poppy_agent.server import (
    AgentRegistrationResponse,
    AgentServerRuntime,
    AgentServerRuntimeError,
    ServerApiError,
    ServerConfig,
    ServerExecutionLifecycleStatus,
    ServerExecutionRecoveryAction,
    ServerExecutionRecoveryResponse,
    ServerExecutionReportStatus,
    ServerExecutionStateResponse,
    ServerTransportError,
)
from poppy_agent.server.client import ServerResponseError
from poppy_agent.server.models import HeartbeatRequest, HeartbeatResponse, ServerExecutionDelivery

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000003")


def config() -> ServerConfig:
    return ServerConfig(
        server_url="https://server.example.test",
        agent_token="test-token",
        agent_name="agent-test",
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="test",
        heartbeat_interval_seconds=0.01,
        execution_poll_interval_seconds=0.01,
        reconnect_initial_delay_seconds=0.01,
        reconnect_max_delay_seconds=0.02,
    )


class IdleTransportServer:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.fail_heartbeat_once = True

    def register_agent(self, _request: object) -> AgentRegistrationResponse:
        self.events.append("register")
        return AgentRegistrationResponse(AGENT_ID, datetime.now(), (ROBOT_ID,), None)

    def send_heartbeat(self, _agent_id: UUID, _request: HeartbeatRequest) -> HeartbeatResponse:
        if self.fail_heartbeat_once:
            self.fail_heartbeat_once = False
            self.events.append("heartbeat-failed")
            raise ServerTransportError("transient")
        self.events.append("heartbeat")
        return HeartbeatResponse(AGENT_ID, datetime.now())

    def fetch_next_execution(self, _agent_id: UUID, _robot_id: UUID) -> None:
        self.events.append("fetch")
        return None

    def close(self) -> None:
        self.events.append("close")


def runtime_for(server: object) -> AgentServerRuntime:
    return AgentServerRuntime(
        create_agent(AgentConfig(robot_mode="mock", robot_id=str(ROBOT_ID))),
        server,  # type: ignore[arg-type]
        config(),
    )


def wait_until(predicate: object, timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        sleep(0.005)
    raise AssertionError("condition did not become true")


def test_idle_transient_failure_degrades_without_polling_until_reconnect() -> None:
    server = IdleTransportServer()
    runtime = runtime_for(server)
    runtime.start()
    stop_event = Event()
    thread = Thread(target=runtime.run_loop, args=(stop_event, object()))
    thread.start()

    wait_until(lambda: "heartbeat-failed" in server.events)
    assert "fetch" not in server.events
    wait_until(lambda: "fetch" in server.events)
    stop_event.set()
    thread.join(timeout=1)
    runtime.shutdown()

    assert not thread.is_alive()
    assert server.events.index("heartbeat-failed") < server.events.index("fetch")


class ActiveTransportServer:
    def __init__(self) -> None:
        self.heartbeat_count = 0
        self.delivery_sent = False
        self.recover_count = 0
        self.status_reports: list[ServerExecutionReportStatus] = []

    def register_agent(self, _request: object) -> AgentRegistrationResponse:
        return AgentRegistrationResponse(AGENT_ID, datetime.now(), (ROBOT_ID,), None)

    def discover_active_execution(self, _agent_id: UUID, _robot_id: UUID) -> None:
        return None

    def send_heartbeat(self, _agent_id: UUID, _request: HeartbeatRequest) -> HeartbeatResponse:
        self.heartbeat_count += 1
        if self.heartbeat_count == 2:
            raise ServerTransportError("transient during execution")
        return HeartbeatResponse(AGENT_ID, datetime.now())

    def fetch_next_execution(
        self, _agent_id: UUID, _robot_id: UUID
    ) -> ServerExecutionDelivery | None:
        if self.delivery_sent:
            return None
        self.delivery_sent = True
        return ServerExecutionDelivery(
            EXECUTION_ID,
            ROBOT_ID,
            "ASSIGNED",
            1,
            '{"protocolVersion":1,"commands":[]}',
        )

    def report_execution_status(
        self,
        _agent_id: UUID,
        _execution_id: UUID,
        _robot_id: UUID,
        status: ServerExecutionReportStatus,
    ) -> object:
        self.status_reports.append(status)
        return object()

    def get_execution_status(
        self, _agent_id: UUID, _execution_id: UUID, _robot_id: UUID
    ) -> ServerExecutionStateResponse:
        return ServerExecutionStateResponse(
            EXECUTION_ID,
            ROBOT_ID,
            ServerExecutionLifecycleStatus.RUNNING,
        )

    def recover_active_execution(
        self, _agent_id: UUID, _robot_id: UUID
    ) -> ServerExecutionRecoveryResponse:
        self.recover_count += 1
        return ServerExecutionRecoveryResponse(
            ROBOT_ID,
            EXECUTION_ID,
            ServerExecutionLifecycleStatus.RUNNING,
            ServerExecutionLifecycleStatus.FAILED,
            ServerExecutionRecoveryAction.RECOVERED_AS_FAILED,
        )

    def close(self) -> None:
        pass


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = Event()
        self.cancelled = False

    def execute(self, _task: ExecutionTask, *, cancellation_token: object) -> ExecutionResult:
        self.started.set()
        while not cancellation_token.is_cancelled():  # type: ignore[attr-defined]
            sleep(0.005)
        self.cancelled = True
        return ExecutionResult(EXECUTION_ID, ExecutionStatus.CANCELLED)


def test_active_transport_failure_interrupts_and_reconciles_without_replay() -> None:
    server = ActiveTransportServer()
    runtime = runtime_for(server)
    runtime.start()
    executor = BlockingExecutor()
    stop_event = Event()
    thread = Thread(target=runtime.run_loop, args=(stop_event, executor))
    thread.start()

    wait_until(executor.started.is_set)
    wait_until(lambda: server.recover_count == 1)
    stop_event.set()
    thread.join(timeout=1)
    runtime.shutdown()

    assert not thread.is_alive()
    assert executor.cancelled
    assert server.status_reports == [ServerExecutionReportStatus.RUNNING]
    assert runtime.active_execution_id is None


def test_invalid_reconnect_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="reconnect delays"):
        ServerConfig(
            server_url="https://server.example.test",
            agent_token="test-token",
            agent_name="agent-test",
            agent_version="0.1.0",
            sdk_version="not-applicable",
            platform="test",
            reconnect_initial_delay_seconds=2.0,
            reconnect_max_delay_seconds=1.0,
        )


def test_runtime_snapshot_tracks_ready_state_and_cleans_status_file(tmp_path) -> None:
    server = IdleTransportServer()
    status_path = tmp_path / "status.json"
    runtime = AgentServerRuntime(
        create_agent(AgentConfig(robot_mode="mock", robot_id=str(ROBOT_ID))),
        server,  # type: ignore[arg-type]
        replace(config(), runtime_status_path=str(status_path)),
    )

    runtime.start()
    snapshot = runtime.operational_snapshot()
    assert snapshot.operational_ready
    assert not snapshot.accepting_new_execution
    assert snapshot.active_execution_id is None
    assert status_path.exists()

    runtime.shutdown()
    assert not status_path.exists()


def test_runtime_distinguishes_transient_auth_and_contract_failures() -> None:
    runtime = runtime_for(IdleTransportServer())

    assert runtime._is_transient_failure(ServerTransportError("timeout"))
    assert runtime._is_transient_failure(ServerApiError(503, "TEMPORARY"))
    assert not runtime._is_transient_failure(ServerApiError(401, "AGENT_AUTH_INVALID"))
    assert not runtime._is_transient_failure(ServerResponseError("malformed"))


def test_nontransient_cancellation_monitor_error_cannot_become_terminal_success() -> None:
    class AuthenticationFailureServer(ActiveTransportServer):
        def __init__(self) -> None:
            super().__init__()
            self.status_checks = 0

        def get_execution_status(
            self, _agent_id: UUID, _execution_id: UUID, _robot_id: UUID
        ) -> ServerExecutionStateResponse:
            self.status_checks += 1
            if self.status_checks > 1:
                raise ServerApiError(401, "AGENT_AUTH_INVALID")
            return super().get_execution_status(_agent_id, _execution_id, _robot_id)

        def send_heartbeat(self, _agent_id: UUID, _request: HeartbeatRequest) -> HeartbeatResponse:
            return HeartbeatResponse(AGENT_ID, datetime.now())

    server = AuthenticationFailureServer()
    runtime = runtime_for(server)
    runtime.start()
    executor = BlockingExecutor()
    stop_event = Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            runtime.run_loop(stop_event, executor)
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=run)
    thread.start()
    wait_until(executor.started.is_set)
    wait_until(lambda: bool(errors))
    stop_event.set()
    thread.join(timeout=1)
    runtime.shutdown()

    assert isinstance(errors[0], AgentServerRuntimeError)
    assert server.status_reports == [
        ServerExecutionReportStatus.RUNNING,
        ServerExecutionReportStatus.FAILED,
    ]
