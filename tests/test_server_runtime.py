import json
import logging
from datetime import datetime
from threading import Event
from uuid import UUID

import httpx
import pytest

from poppy_agent.agent import create_agent
from poppy_agent.command import CommandType, HighLevelCommandProgram, StopParameters
from poppy_agent.config import AgentConfig
from poppy_agent.execution import (
    ExecutionCancellationToken,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTask,
    MockExecutionExecutor,
)
from poppy_agent.observability import (
    AGENT_REGISTERED,
    EXECUTION_RECOVERY_CHECKED,
    EXECUTION_RECOVERY_NO_ACTIVE,
    RUNTIME_READY,
)
from poppy_agent.server import (
    AgentRegistrationResponse,
    AgentServerRuntime,
    AgentServerRuntimeError,
    HeartbeatRequest,
    HeartbeatResponse,
    ServerActiveExecutionResponse,
    ServerApiError,
    ServerClient,
    ServerConfig,
    ServerExecutionLifecycleStatus,
    ServerExecutionRecoveryAction,
    ServerExecutionRecoveryResponse,
    ServerExecutionReportStatus,
    ServerExecutionStateResponse,
    ServerExecutionStatusResponse,
)
from poppy_agent.server.models import ServerExecutionDelivery

ROBOT_ID = "00000000-0000-0000-0000-000000000001"
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000003")
OTHER_EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000004")
COMMAND_PAYLOAD = '{"protocolVersion":1,"commands":[]}'


class RecordingServer:
    def __init__(self, deliveries: list[ServerExecutionDelivery | None]) -> None:
        self.deliveries = deliveries
        self.events: list[str] = []
        self.heartbeat_requests: list[HeartbeatRequest] = []
        self.status_reports: list[ServerExecutionReportStatus] = []
        self.fail_statuses: set[ServerExecutionReportStatus] = set()

    def register_agent(self, _request: object) -> AgentRegistrationResponse:
        self.events.append("register")
        return AgentRegistrationResponse(
            agent_id=AGENT_ID,
            registered_at=datetime(2026, 8, 25, 10, 20, 30),
            accepted_robot_ids=(UUID(ROBOT_ID),),
            agent_token="issued-agent-token",
        )

    def send_heartbeat(self, _agent_id: UUID, request: HeartbeatRequest) -> HeartbeatResponse:
        self.events.append("heartbeat")
        self.heartbeat_requests.append(request)
        return HeartbeatResponse(agent_id=AGENT_ID, accepted_at=datetime.now())

    def fetch_next_execution(
        self, _agent_id: UUID, _robot_id: UUID
    ) -> ServerExecutionDelivery | None:
        self.events.append("fetch")
        return self.deliveries.pop(0) if self.deliveries else None

    def report_execution_status(
        self,
        _agent_id: UUID,
        _execution_id: UUID,
        _robot_id: UUID,
        status: ServerExecutionReportStatus,
    ) -> ServerExecutionStatusResponse:
        self.events.append(f"report:{status.value}")
        self.status_reports.append(status)
        if status in self.fail_statuses:
            raise ServerApiError(409, "STATUS_CONFLICT")
        return ServerExecutionStatusResponse(
            execution_id=_execution_id,
            robot_id=_robot_id,
            status=status,
        )

    def close(self) -> None:
        self.events.append("close")


def runtime_with_recording_server(
    server: RecordingServer, *, poll_interval: float = 1.0, heartbeat_interval: float = 30.0
) -> AgentServerRuntime:
    config = ServerConfig(
        server_url="https://server.example.test",
        agent_token="dummy-agent-token",
        agent_name="agent-test",
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="test",
        heartbeat_interval_seconds=heartbeat_interval,
        execution_poll_interval_seconds=poll_interval,
    )
    agent = create_agent(AgentConfig(robot_mode="mock", robot_id=ROBOT_ID))
    return AgentServerRuntime(agent, server, config)  # type: ignore[arg-type]


def assigned_delivery(
    execution_id: UUID = EXECUTION_ID, command_payload: str = COMMAND_PAYLOAD
) -> ServerExecutionDelivery:
    return ServerExecutionDelivery(
        execution_id=execution_id,
        robot_id=UUID(ROBOT_ID),
        status="ASSIGNED",
        protocol_version=1,
        command_payload=command_payload,
    )


def runtime_with_mock_server(handler, *, robot_id: str = ROBOT_ID):
    server_config = ServerConfig(
        server_url="https://server.example.test",
        agent_token="dummy-agent-token",
        agent_name="agent-test",
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="test",
        heartbeat_interval_seconds=30,
    )
    client = ServerClient(server_config, transport=httpx.MockTransport(handler))
    agent = create_agent(AgentConfig(robot_mode="mock", robot_id=robot_id))
    return AgentServerRuntime(agent, client, server_config)


def test_start_reconciles_active_execution_before_runtime_can_poll() -> None:
    class RecoveryServer(RecordingServer):
        def discover_active_execution(
            self, _agent_id: UUID, robot_id: UUID
        ) -> ServerActiveExecutionResponse:
            self.events.append("discover")
            return ServerActiveExecutionResponse(
                EXECUTION_ID,
                robot_id,
                ServerExecutionLifecycleStatus.RUNNING,
            )

        def recover_active_execution(
            self, _agent_id: UUID, robot_id: UUID
        ) -> ServerExecutionRecoveryResponse:
            self.events.append("recover")
            return ServerExecutionRecoveryResponse(
                robot_id,
                EXECUTION_ID,
                ServerExecutionLifecycleStatus.RUNNING,
                ServerExecutionLifecycleStatus.FAILED,
                ServerExecutionRecoveryAction.RECOVERED_AS_FAILED,
            )

    server = RecoveryServer([])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    assert server.events == ["register", "discover", "recover"]
    assert runtime.active_execution_id is None
    runtime.shutdown()


def test_runtime_start_logs_registration_and_recovery_state(caplog) -> None:
    server = RecordingServer([])
    runtime = runtime_with_recording_server(server)

    with caplog.at_level(logging.INFO, logger="poppy_agent.server.runtime"):
        runtime.start()
        runtime.shutdown()

    events = [record.poppy_event for record in caplog.records]
    assert AGENT_REGISTERED in events
    assert EXECUTION_RECOVERY_CHECKED in events
    assert EXECUTION_RECOVERY_NO_ACTIVE in events
    assert RUNTIME_READY in events


def test_recovery_failure_stops_startup_before_heartbeat_or_polling() -> None:
    class FailingRecoveryServer(RecordingServer):
        def discover_active_execution(self, _agent_id: UUID, _robot_id: UUID) -> None:
            self.events.append("discover")
            raise RuntimeError("recovery unavailable")

        def recover_active_execution(
            self, _agent_id: UUID, _robot_id: UUID
        ) -> ServerExecutionRecoveryResponse:
            raise AssertionError("recovery must not run after discovery failure")

    server = FailingRecoveryServer([])
    runtime = runtime_with_recording_server(server)

    with pytest.raises(RuntimeError, match="recovery unavailable"):
        runtime.start()

    assert server.events == ["register", "discover"]
    runtime.shutdown()


def test_runtime_registers_mock_robot_and_sends_heartbeat() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/register"):
            body = json.loads(request.content)
            assert body["robots"][0]["robotId"] == ROBOT_ID
            return httpx.Response(
                201,
                json={
                    "success": True,
                    "data": {
                        "agentId": str(AGENT_ID),
                        "registeredAt": "2026-08-25T10:20:30",
                        "acceptedRobotIds": [ROBOT_ID],
                        "agentToken": "issued-agent-token",
                    },
                    "error": None,
                },
            )
        if request.url.path.endswith("/active-execution"):
            assert request.method == "GET"
            assert request.headers["X-Agent-Token"] == "issued-agent-token"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"activeExecution": None},
                    "error": None,
                },
            )
        assert request.headers["X-Agent-Token"] == "issued-agent-token"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"agentId": str(AGENT_ID), "acceptedAt": "2026-08-25T10:20:31"},
                "error": None,
            },
        )

    runtime = runtime_with_mock_server(handler)
    registration = runtime.start()
    heartbeat = runtime.heartbeat_once()
    runtime.shutdown()

    assert registration.agent_id == AGENT_ID
    assert heartbeat.agent_id == AGENT_ID
    assert paths == [
        "/api/v1/internal/agents/register",
        f"/api/v1/internal/agents/{AGENT_ID}/robots/{ROBOT_ID}/active-execution",
        f"/api/v1/internal/agents/{AGENT_ID}/heartbeat",
    ]


def test_runtime_rejects_non_uuid_robot_identity_before_http_request() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    runtime = runtime_with_mock_server(handler, robot_id="test-robot")
    with pytest.raises(AgentServerRuntimeError, match="must be a UUID"):
        runtime.start()

    assert calls == 0
    runtime.shutdown()


def test_execution_requires_registration() -> None:
    runtime = runtime_with_recording_server(RecordingServer([]))

    with pytest.raises(AgentServerRuntimeError, match="registered before execution"):
        runtime.execution_once(lambda _: None)  # type: ignore[arg-type]
    runtime.shutdown()


def test_execution_no_work_does_not_call_executor() -> None:
    server = RecordingServer([None])
    runtime = runtime_with_recording_server(server)
    runtime.start()
    calls = 0

    def executor(_task: ExecutionTask) -> ExecutionResult:
        nonlocal calls
        calls += 1
        return ExecutionResult(EXECUTION_ID, ExecutionStatus.COMPLETED)

    assert runtime.execution_once(executor) is None  # type: ignore[arg-type]
    runtime.shutdown()

    assert calls == 0
    assert server.status_reports == []
    assert runtime.active_execution_id is None


@pytest.mark.parametrize(
    ("status", "protocol_version", "message"),
    [("RUNNING", 1, "status"), ("ASSIGNED", 2, "unsupported execution protocol")],
)
def test_execution_rejects_invalid_delivery_metadata(
    status: str, protocol_version: int, message: str
) -> None:
    delivery = ServerExecutionDelivery(
        execution_id=EXECUTION_ID,
        robot_id=UUID(ROBOT_ID),
        status=status,
        protocol_version=protocol_version,
        command_payload=COMMAND_PAYLOAD,
    )
    server = RecordingServer([delivery])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    with pytest.raises((AgentServerRuntimeError, ValueError), match=message):
        runtime.execution_once(lambda _task: None)  # type: ignore[arg-type]
    runtime.shutdown()

    expected_reports = [] if status == "RUNNING" else [ServerExecutionReportStatus.FAILED]
    assert server.status_reports == expected_reports


def test_execution_success_reports_running_before_completed() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    class SuccessExecutor:
        def execute(self, task: ExecutionTask) -> ExecutionResult:
            server.events.append("execute")
            assert runtime.active_execution_id == EXECUTION_ID
            assert isinstance(task.command_program, HighLevelCommandProgram)
            assert task.command_program.commands == ()
            return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)

    result = runtime.execution_once(SuccessExecutor())
    runtime.shutdown()

    assert result is not None
    assert result.status is ExecutionStatus.COMPLETED
    assert server.events == [
        "register",
        "fetch",
        "report:RUNNING",
        "execute",
        "report:COMPLETED",
        "close",
    ]
    assert runtime.active_execution_id is None


def test_execution_parses_typed_command_program_before_running() -> None:
    command_payload = (
        '{"protocolVersion":1,"commands":['
        '{"sequence":0,"sourceBlockId":"stop-1","type":"STOP","parameters":{}}]}'
    )
    server = RecordingServer([assigned_delivery(command_payload=command_payload)])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    class InspectingExecutor:
        def execute(self, task: ExecutionTask) -> ExecutionResult:
            assert task.command_program.commands[0].type is CommandType.STOP
            assert isinstance(task.command_program.commands[0].parameters, StopParameters)
            return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)

    result = runtime.execution_once(InspectingExecutor())
    runtime.shutdown()

    assert result is not None


def test_runtime_executes_typed_program_with_mock_executor_and_reports_completion() -> None:
    command_payload = (
        '{"protocolVersion":1,"commands":['
        '{"sequence":0,"sourceBlockId":"wait-1","type":"WAIT",'
        '"parameters":{"durationSeconds":30}},'
        '{"sequence":1,"sourceBlockId":"stop-1","type":"STOP","parameters":{}},'
        '{"sequence":2,"sourceBlockId":"after-stop","type":"WAIT",'
        '"parameters":{"durationSeconds":999}}]}'
    )
    server = RecordingServer([assigned_delivery(command_payload=command_payload)])
    runtime = runtime_with_recording_server(server)
    runtime.start()
    executor = MockExecutionExecutor()

    result = runtime.execution_once(executor)
    runtime.shutdown()

    assert result == ExecutionResult(EXECUTION_ID, ExecutionStatus.COMPLETED)
    assert [event.sequence for event in executor.events] == [0, 1]
    assert [event.source_block_id for event in executor.events] == ["wait-1", "stop-1"]
    assert [event.type for event in executor.events] == [CommandType.WAIT, CommandType.STOP]
    assert server.status_reports == [
        ServerExecutionReportStatus.RUNNING,
        ServerExecutionReportStatus.COMPLETED,
    ]


@pytest.mark.parametrize("command_payload", ["{", '{"protocolVersion":1,"commands":[],"extra":1}'])
def test_execution_rejects_invalid_command_payload_before_running(
    command_payload: str,
) -> None:
    server = RecordingServer([assigned_delivery(command_payload=command_payload)])
    runtime = runtime_with_recording_server(server)
    runtime.start()
    calls = 0

    def executor(_task: ExecutionTask) -> ExecutionResult:
        nonlocal calls
        calls += 1
        return ExecutionResult(EXECUTION_ID, ExecutionStatus.COMPLETED)

    if command_payload == "{":
        with pytest.raises(ValueError, match="malformed"):
            runtime.execution_once(executor)
    else:
        with pytest.raises(ValueError):
            runtime.execution_once(executor)
    runtime.shutdown()

    assert calls == 0
    assert server.status_reports == [ServerExecutionReportStatus.FAILED]
    assert runtime.active_execution_id is None


def test_execution_failure_result_reports_failed() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    result = runtime.execution_once(
        type(
            "FailureExecutor",
            (),
            {
                "execute": lambda _self, task: ExecutionResult(
                    task.execution_id, ExecutionStatus.FAILED
                )
            },
        )()
    )
    runtime.shutdown()

    assert result is not None
    assert result.status is ExecutionStatus.FAILED
    assert server.status_reports == [
        ServerExecutionReportStatus.RUNNING,
        ServerExecutionReportStatus.FAILED,
    ]


def test_running_report_failure_does_not_execute_or_leave_active_execution() -> None:
    server = RecordingServer([assigned_delivery()])
    server.fail_statuses.add(ServerExecutionReportStatus.RUNNING)
    runtime = runtime_with_recording_server(server)
    runtime.start()
    calls = 0

    class Executor:
        def execute(self, _task: ExecutionTask) -> ExecutionResult:
            nonlocal calls
            calls += 1
            raise AssertionError("executor must not run")

    with pytest.raises(ServerApiError):
        runtime.execution_once(Executor())
    runtime.shutdown()

    assert calls == 0
    assert runtime.active_execution_id is None


def test_final_report_failure_propagates_and_keeps_active_execution() -> None:
    server = RecordingServer([assigned_delivery()])
    server.fail_statuses.add(ServerExecutionReportStatus.COMPLETED)
    runtime = runtime_with_recording_server(server)
    runtime.start()

    with pytest.raises(ServerApiError):
        runtime.execution_once(
            type(
                "SuccessExecutor",
                (),
                {
                    "execute": lambda _self, task: ExecutionResult(
                        task.execution_id, ExecutionStatus.COMPLETED
                    )
                },
            )()
        )
    runtime.shutdown()

    assert runtime.active_execution_id == EXECUTION_ID


def test_active_execution_blocks_a_second_poll() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server)
    runtime.start()
    runtime.active_execution_id = EXECUTION_ID

    with pytest.raises(AgentServerRuntimeError, match="already active"):
        runtime.execution_once(lambda _task: None)  # type: ignore[arg-type]
    runtime.shutdown()

    assert server.events == ["register", "close"]


def test_executor_exception_best_effort_reports_failed_and_propagates() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    class RaisingExecutor:
        def execute(self, _task: ExecutionTask) -> ExecutionResult:
            raise RuntimeError("executor failure")

    with pytest.raises(RuntimeError, match="executor failure"):
        runtime.execution_once(RaisingExecutor())
    runtime.shutdown()

    assert server.status_reports == [
        ServerExecutionReportStatus.RUNNING,
        ServerExecutionReportStatus.FAILED,
    ]
    assert runtime.active_execution_id is None


def test_execution_result_identity_mismatch_is_rejected() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    with pytest.raises(AgentServerRuntimeError, match="identity"):
        runtime.execution_once(
            type(
                "WrongResultExecutor",
                (),
                {
                    "execute": lambda _self, _task: ExecutionResult(
                        OTHER_EXECUTION_ID, ExecutionStatus.COMPLETED
                    )
                },
            )()
        )
    runtime.shutdown()

    assert server.status_reports == [
        ServerExecutionReportStatus.RUNNING,
        ServerExecutionReportStatus.FAILED,
    ]
    assert runtime.active_execution_id is None


def test_heartbeat_uses_active_execution_and_omits_idle_execution_field() -> None:
    server = RecordingServer([])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    runtime.heartbeat_once()
    runtime.active_execution_id = EXECUTION_ID
    runtime.heartbeat_once()
    runtime.active_execution_id = None
    runtime.heartbeat_once()
    runtime.shutdown()

    idle_before = server.heartbeat_requests[0].robots[0]
    active = server.heartbeat_requests[1].robots[0]
    idle_after = server.heartbeat_requests[2].robots[0]
    assert idle_before.current_execution_id_provided is False
    assert active.current_execution_id_provided is True
    assert active.current_execution_id == EXECUTION_ID
    assert idle_after.current_execution_id_provided is False
    assert "currentExecutionId" not in idle_after.to_json()


def test_run_loop_schedules_heartbeat_and_execution_poll_separately() -> None:
    server = RecordingServer([None])
    runtime = runtime_with_recording_server(server, poll_interval=1)
    runtime.start()

    class StopAfterWait(Event):
        def __init__(self) -> None:
            super().__init__()
            self.waits: list[float] = []

        def wait(self, timeout: float | None = None) -> bool:
            assert timeout is not None
            self.waits.append(timeout)
            self.set()
            return True

    stop_event = StopAfterWait()
    runtime.run_loop(stop_event, type("Executor", (), {})())  # type: ignore[arg-type]
    runtime.shutdown()

    assert server.events[:3] == ["register", "heartbeat", "fetch"]
    assert stop_event.waits
    assert 0 < stop_event.waits[0] <= 1


def test_run_loop_keeps_heartbeat_and_stop_responsive_while_executor_blocks() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server, poll_interval=0.01, heartbeat_interval=0.01)
    runtime.start()
    executor_started = Event()
    release_executor = Event()

    class BlockingExecutor:
        def execute(self, task: ExecutionTask) -> ExecutionResult:
            executor_started.set()
            release_executor.wait()
            return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)

    class StopAfterSecondHeartbeat(Event):
        def wait(self, timeout: float | None = None) -> bool:
            super().wait(min(timeout or 0.005, 0.005))
            if len(server.heartbeat_requests) >= 2:
                self.set()
            return self.is_set()

    stop_event = StopAfterSecondHeartbeat()
    runtime.run_loop(stop_event, BlockingExecutor())
    assert executor_started.is_set()
    assert len(server.heartbeat_requests) >= 2
    assert runtime.active_execution_id == EXECUTION_ID

    release_executor.set()
    runtime.shutdown()


def test_run_loop_propagates_server_cancellation_to_running_executor() -> None:
    class CancellableServer(RecordingServer):
        def __init__(self) -> None:
            super().__init__([assigned_delivery()])
            self.status_reads = 0
            self.stop_event: Event | None = None

        def get_execution_status(
            self, _agent_id: UUID, _execution_id: UUID, _robot_id: UUID
        ) -> ServerExecutionStateResponse:
            self.status_reads += 1
            status = (
                ServerExecutionLifecycleStatus.RUNNING
                if self.status_reads == 1
                else ServerExecutionLifecycleStatus.CANCELLED
            )
            return ServerExecutionStateResponse(EXECUTION_ID, UUID(ROBOT_ID), status)

        def report_execution_status(
            self,
            agent_id: UUID,
            execution_id: UUID,
            robot_id: UUID,
            status: ServerExecutionReportStatus,
        ) -> ServerExecutionStatusResponse:
            response = super().report_execution_status(agent_id, execution_id, robot_id, status)
            if status is ServerExecutionReportStatus.CANCELLED and self.stop_event is not None:
                self.stop_event.set()
            return response

    server = CancellableServer()
    runtime = runtime_with_recording_server(server, poll_interval=0.01, heartbeat_interval=1.0)
    runtime.start()
    stop_event = Event()
    server.stop_event = stop_event
    executor_started = Event()

    class CancellableExecutor:
        def execute(
            self,
            task: ExecutionTask,
            cancellation_token: ExecutionCancellationToken | None = None,
        ) -> ExecutionResult:
            assert cancellation_token is not None
            executor_started.set()
            while not cancellation_token.is_cancelled():
                Event().wait(0.01)
            return ExecutionResult(task.execution_id, ExecutionStatus.CANCELLED)

    runtime.run_loop(stop_event, CancellableExecutor())
    runtime.shutdown()

    assert executor_started.is_set()
    assert server.status_reports == [
        ServerExecutionReportStatus.RUNNING,
        ServerExecutionReportStatus.CANCELLED,
    ]
    assert runtime.active_execution_id is None
