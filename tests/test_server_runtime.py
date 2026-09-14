import json
from datetime import datetime
from threading import Event
from uuid import UUID

import httpx
import pytest

from poppy_agent.agent import create_agent
from poppy_agent.config import AgentConfig
from poppy_agent.execution import ExecutionResult, ExecutionStatus, ExecutionTask
from poppy_agent.server import (
    AgentRegistrationResponse,
    AgentServerRuntime,
    AgentServerRuntimeError,
    HeartbeatRequest,
    HeartbeatResponse,
    ServerApiError,
    ServerClient,
    ServerConfig,
    ServerExecutionReportStatus,
    ServerExecutionStatusResponse,
)
from poppy_agent.server.models import ServerExecutionDelivery

ROBOT_ID = "00000000-0000-0000-0000-000000000001"
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000003")
OTHER_EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000004")


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
    server: RecordingServer, *, poll_interval: float = 1.0
) -> AgentServerRuntime:
    config = ServerConfig(
        server_url="https://server.example.test",
        agent_token="dummy-agent-token",
        agent_name="agent-test",
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="test",
        heartbeat_interval_seconds=30,
        execution_poll_interval_seconds=poll_interval,
    )
    agent = create_agent(AgentConfig(robot_mode="mock", robot_id=ROBOT_ID))
    return AgentServerRuntime(agent, server, config)  # type: ignore[arg-type]


def assigned_delivery(execution_id: UUID = EXECUTION_ID) -> ServerExecutionDelivery:
    return ServerExecutionDelivery(
        execution_id=execution_id,
        robot_id=UUID(ROBOT_ID),
        status="ASSIGNED",
        protocol_version=1,
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
                    },
                    "error": None,
                },
            )
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
    )
    server = RecordingServer([delivery])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    with pytest.raises((AgentServerRuntimeError, ValueError), match=message):
        runtime.execution_once(lambda _task: None)  # type: ignore[arg-type]
    runtime.shutdown()

    assert server.status_reports == []


def test_execution_success_reports_running_before_completed() -> None:
    server = RecordingServer([assigned_delivery()])
    runtime = runtime_with_recording_server(server)
    runtime.start()

    class SuccessExecutor:
        def execute(self, task: ExecutionTask) -> ExecutionResult:
            server.events.append("execute")
            assert runtime.active_execution_id == EXECUTION_ID
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

    assert server.status_reports == [ServerExecutionReportStatus.RUNNING]


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
