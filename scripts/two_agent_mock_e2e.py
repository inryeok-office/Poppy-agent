"""Run the two-Robot/two-Agent isolation scenario over real local HTTP."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import UUID, uuid4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from full_mock_e2e import (  # noqa: E402
    COMMAND_CAPABILITIES,
    E2EConfig,
    E2EHttpClient,
    FullMockE2EError,
    RecordingServerClient,
    _assert,
    _execution_status,
    _find_robot,
    _required_int,
    _required_string,
    _wait_for,
)

from poppy_agent.agent import create_agent  # noqa: E402
from poppy_agent.config import AgentConfig  # noqa: E402
from poppy_agent.execution import ExecutionResult, ExecutionStatus  # noqa: E402
from poppy_agent.server import (  # noqa: E402
    AgentRegistrationResponse,
    AgentServerRuntime,
    HeartbeatRequest,
    HeartbeatRobotRequest,
    ServerConfig,
    ServerExecutionReportStatus,
)


@dataclass(slots=True)
class AgentFixture:
    name: str
    robot_id: UUID
    runtime: AgentServerRuntime
    client: RecordingServerClient
    registration: AgentRegistrationResponse
    runtime_token: str


class GateExecutor:
    """Hold an execution at its command boundary until the test releases it."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def execute(self, task: Any) -> ExecutionResult:
        self.started.set()
        if not self.release.wait(10.0):
            raise RuntimeError("two-agent E2E executor release timed out")
        return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)


class CooperativeCancellationExecutor:
    """Wait for the runtime cancellation token without touching hardware."""

    def __init__(self) -> None:
        self.started = Event()

    def execute(self, task: Any, *, cancellation_token: Any) -> ExecutionResult:
        self.started.set()
        while not cancellation_token.is_cancelled():
            sleep(0.01)
        return ExecutionResult(task.execution_id, ExecutionStatus.CANCELLED)


class SimulatedCrashExecutor:
    """Model process state loss; it never sends a terminal execution report."""

    def execute(self, _task: Any) -> ExecutionResult:
        raise KeyboardInterrupt("simulated Agent interruption")


def main() -> int:
    config = E2EConfig.from_environment()
    http = E2EHttpClient(config.server_url, config.http_timeout_seconds, config.agent_token)
    run_id = uuid4().hex
    agent_a: AgentFixture | None = None
    agent_b: AgentFixture | None = None
    try:
        robot_a = _create_robot(http, f"two-agent-{run_id}-a")
        robot_b = _create_robot(http, f"two-agent-{run_id}-b")

        session_a, execution_a = _create_execution(http, "A")
        agent_a = _start_agent(config, robot_a, f"two-agent-{run_id}-a")
        _prepare_robot(http, agent_a)
        _wait_for_assignment(http, session_a, execution_a, robot_a, config)

        session_b, execution_b = _create_execution(http, "B")
        agent_b = _start_agent(config, robot_b, f"two-agent-{run_id}-b")
        _prepare_robot(http, agent_b)
        _wait_for_assignment(http, session_b, execution_b, robot_b, config)

        _assert(agent_a.runtime_token != agent_b.runtime_token, "runtime credentials are shared")
        _assert_credential_isolation(config, agent_a, agent_b)
        print("Two Agent registrations and runtime credential isolation confirmed")

        _run_concurrent_completion(
            http,
            config,
            agent_a,
            agent_b,
            session_a,
            execution_a,
            session_b,
            execution_b,
        )
        print("Concurrent execution and Robot ownership isolation confirmed")

        _run_cancellation_isolation(http, config, agent_a, agent_b)
        print("Cancellation isolation confirmed: one terminal path did not affect the other")

        agent_a, agent_b = _run_crash_recovery_isolation(http, config, agent_a, agent_b)
        print(
            "Crash recovery isolation confirmed: replay=0 and only the interrupted Robot released"
        )

        _assert_no_work(agent_a, agent_b)
        print("Both Agent runtimes returned no work after terminal reconciliation")
        print("TWO ROBOT / TWO AGENT CONCURRENT FULL MOCK E2E PASSED")
        return 0
    finally:
        if agent_a is not None:
            agent_a.runtime.shutdown()
        if agent_b is not None:
            agent_b.runtime.shutdown()


def _create_robot(http: E2EHttpClient, alias: str) -> UUID:
    data = http.post(
        "/api/v1/admin/robots",
        {
            "alias": alias,
            "model": "mock",
            "edition": "development",
            "firmwareVersion": "mock",
            "sdkVersion": "not-applicable",
            "agentId": None,
            "capabilities": [],
            "safetyProfileId": None,
            "isExternal": False,
        },
        expected_status=201,
    )
    return UUID(_required_string(data, "robotId"))


def _create_execution(http: E2EHttpClient, label: str) -> tuple[str, UUID]:
    session = http.post("/api/v1/sessions", {}, expected_status=201)
    session_id = _required_string(session, "sessionId")
    session_token = _required_string(session, "sessionToken")
    revision = http.post(
        f"/api/v1/sessions/{session_id}/block-revisions",
        {"document": _block_program()},
        expected_status=201,
        session_token=session_token,
    )
    block_version = _required_int(revision, "blockVersion")
    http.post(
        f"/api/v1/sessions/{session_id}/simulation-passes",
        {"blockVersion": block_version},
        expected_status=201,
        session_token=session_token,
    )
    execution = http.post(
        f"/api/v1/sessions/{session_id}/executions",
        {"blockVersion": block_version},
        expected_status=201,
        session_token=session_token,
    )
    execution_id = UUID(_required_string(execution, "executionId"))
    _assert(_required_string(execution, "status") == "QUEUED", f"Execution {label} is not QUEUED")
    return session_token, execution_id


def _start_agent(config: E2EConfig, robot_id: UUID, name: str) -> AgentFixture:
    server_config = ServerConfig(
        server_url=config.server_url,
        agent_token=config.agent_token,
        agent_name=name,
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="two-agent-e2e",
        heartbeat_interval_seconds=30.0,
        execution_poll_interval_seconds=config.poll_interval_seconds,
        connect_timeout_seconds=config.http_timeout_seconds,
        read_timeout_seconds=config.http_timeout_seconds,
        max_retries=0,
    )
    client = RecordingServerClient(server_config)
    runtime = AgentServerRuntime(
        create_agent(AgentConfig(robot_mode="mock", robot_id=str(robot_id))),
        client,
        server_config,
    )
    _assert(runtime.config.server_url.startswith("http://localhost"), "non-local E2E target")
    registration = runtime.start()
    _assert(robot_id in registration.accepted_robot_ids, "Agent did not accept its Robot")
    runtime_token = registration.agent_token
    _assert(runtime_token is not None and runtime_token.strip(), "runtime token was not issued")
    return AgentFixture(name, robot_id, runtime, client, registration, runtime_token)


def _prepare_robot(http: E2EHttpClient, agent: AgentFixture) -> None:
    capabilities = [{"code": "telemetry", "status": "UNVERIFIED"}]
    capabilities.extend(
        {"code": code, "status": "VERIFIED"} for code in sorted(COMMAND_CAPABILITIES)
    )
    http.patch(f"/api/v1/admin/robots/{agent.robot_id}", {"capabilities": capabilities})
    agent.runtime.heartbeat_once()
    ready = _wait_for(
        f"Robot {agent.robot_id} ready",
        lambda: _find_robot(http, agent.robot_id),
        lambda value: (
            value.get("connectionStatus") == "ONLINE"
            and value.get("operationalStatus") == "READY"
            and value.get("occupied") is False
        ),
        _config_from_environment(),
    )
    _assert(ready.get("currentExecutionId") is None, "Robot unexpectedly owns an execution")


def _wait_for_assignment(
    http: E2EHttpClient,
    session_token: str,
    execution_id: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> None:
    status = _wait_for(
        f"Execution {execution_id} ASSIGNED",
        lambda: _execution_status(http, session_token, execution_id),
        lambda value: (
            value.get("status") == "ASSIGNED" and value.get("assignedRobotId") == str(robot_id)
        ),
        config,
    )
    _assert(status.get("assignedRobotId") == str(robot_id), "Execution assigned to wrong Robot")


def _wait_for_any_assignment(
    http: E2EHttpClient,
    session_token: str,
    execution_id: UUID,
    robot_ids: set[UUID],
    config: E2EConfig,
) -> UUID:
    status = _wait_for(
        f"Execution {execution_id} ASSIGNED",
        lambda: _execution_status(http, session_token, execution_id),
        lambda value: (
            value.get("status") == "ASSIGNED"
            and value.get("assignedRobotId") in {str(robot_id) for robot_id in robot_ids}
        ),
        config,
    )
    return UUID(_required_string(status, "assignedRobotId"))


def _run_concurrent_completion(
    http: E2EHttpClient,
    config: E2EConfig,
    agent_a: AgentFixture,
    agent_b: AgentFixture,
    session_a: str,
    execution_a: UUID,
    session_b: str,
    execution_b: UUID,
) -> None:
    executor_a = GateExecutor()
    executor_b = GateExecutor()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="two-agent-e2e") as pool:
        future_a = pool.submit(agent_a.runtime.execution_once, executor_a)
        future_b = pool.submit(agent_b.runtime.execution_once, executor_b)
        _wait_event(executor_a.started, config)
        _wait_event(executor_b.started, config)
        _assert_running(http, config, session_a, execution_a, session_b, execution_b)
        _assert(agent_a.runtime.active_execution_id == execution_a, "Agent A active ID mismatch")
        _assert(agent_b.runtime.active_execution_id == execution_b, "Agent B active ID mismatch")
        executor_a.release.set()
        executor_b.release.set()
        result_a = future_a.result(timeout=config.timeout_seconds)
        result_b = future_b.result(timeout=config.timeout_seconds)
    _assert(
        result_a is not None and result_a.status is ExecutionStatus.COMPLETED, "A did not complete"
    )
    _assert(
        result_b is not None and result_b.status is ExecutionStatus.COMPLETED, "B did not complete"
    )
    _assert(
        agent_a.client.reported_statuses
        == [ServerExecutionReportStatus.RUNNING, ServerExecutionReportStatus.COMPLETED],
        "A report order mismatch",
    )
    _assert(
        agent_b.client.reported_statuses
        == [ServerExecutionReportStatus.RUNNING, ServerExecutionReportStatus.COMPLETED],
        "B report order mismatch",
    )
    _assert_terminal_and_released(http, config, session_a, execution_a, agent_a.robot_id)
    _assert_terminal_and_released(http, config, session_b, execution_b, agent_b.robot_id)


def _run_cancellation_isolation(
    http: E2EHttpClient, config: E2EConfig, agent_a: AgentFixture, agent_b: AgentFixture
) -> None:
    session_a, execution_a = _create_execution(http, "cancel-A")
    session_b, execution_b = _create_execution(http, "cancel-B")
    assigned_a = _wait_for_any_assignment(
        http, session_a, execution_a, {agent_a.robot_id, agent_b.robot_id}, config
    )
    assigned_b = _wait_for_any_assignment(
        http, session_b, execution_b, {agent_a.robot_id, agent_b.robot_id}, config
    )
    _assert(assigned_a != assigned_b, "cancellation executions shared one Robot")
    cancelled_agent = agent_a if assigned_a == agent_a.robot_id else agent_b
    normal_agent = agent_b if cancelled_agent is agent_a else agent_a
    cancelled_session = session_a if cancelled_agent is agent_a else session_b
    cancelled_execution = execution_a if cancelled_agent is agent_a else execution_b
    normal_session = session_b if cancelled_agent is agent_a else session_a
    normal_execution = execution_b if cancelled_agent is agent_a else execution_a
    cancel_executor = CooperativeCancellationExecutor()
    normal_executor = GateExecutor()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="two-agent-cancel-e2e") as pool:
        future_cancel = pool.submit(cancelled_agent.runtime.execution_once, cancel_executor)
        future_normal = pool.submit(normal_agent.runtime.execution_once, normal_executor)
        _wait_event(cancel_executor.started, config)
        _wait_event(normal_executor.started, config)
        _assert_running(
            http,
            config,
            cancelled_session,
            cancelled_execution,
            normal_session,
            normal_execution,
        )
        http.post(
            f"/api/v1/executions/{cancelled_execution}/cancel",
            {},
            expected_status=200,
            session_token=cancelled_session,
        )
        result_cancel = future_cancel.result(timeout=config.timeout_seconds)
        _assert(
            result_cancel is not None and result_cancel.status is ExecutionStatus.CANCELLED,
            "cancelled execution did not return CANCELLED",
        )
        still_running = _execution_status(http, normal_session, normal_execution)
        _assert(still_running.get("status") == "RUNNING", "B changed during A cancellation")
        normal_executor.release.set()
        result_normal = future_normal.result(timeout=config.timeout_seconds)
    _assert(
        result_normal is not None and result_normal.status is ExecutionStatus.COMPLETED,
        "unaffected execution did not complete",
    )
    _assert_terminal_and_released(
        http, config, cancelled_session, cancelled_execution, cancelled_agent.robot_id, "CANCELLED"
    )
    _assert_terminal_and_released(
        http, config, normal_session, normal_execution, normal_agent.robot_id
    )


def _run_crash_recovery_isolation(
    http: E2EHttpClient,
    config: E2EConfig,
    agent_a: AgentFixture,
    agent_b: AgentFixture,
) -> tuple[AgentFixture, AgentFixture]:
    session_a, execution_a = _create_execution(http, "crash-A")
    assigned = _wait_for(
        f"Execution {execution_a} ASSIGNED",
        lambda: _execution_status(http, session_a, execution_a),
        lambda value: (
            value.get("status") == "ASSIGNED"
            and value.get("assignedRobotId") in {str(agent_a.robot_id), str(agent_b.robot_id)}
        ),
        config,
    )
    assigned_robot_id = UUID(_required_string(assigned, "assignedRobotId"))
    interrupted = agent_a if assigned_robot_id == agent_a.robot_id else agent_b
    unaffected = agent_b if interrupted is agent_a else agent_a
    errors: list[BaseException] = []

    def crash() -> None:
        try:
            interrupted.runtime.execution_once(SimulatedCrashExecutor())
        except BaseException as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="two-agent-crash-e2e") as pool:
        pool.submit(crash).result(timeout=config.timeout_seconds)
    _assert(errors and isinstance(errors[0], KeyboardInterrupt), "crash was not simulated")
    active = _execution_status(http, session_a, execution_a)
    _assert(active.get("status") == "RUNNING", "crash did not preserve RUNNING state")
    _assert(
        interrupted.runtime.active_execution_id == execution_a,
        "crashed Agent lost diagnostic ownership",
    )
    _assert(
        _find_robot(http, unaffected.robot_id).get("occupied") is False,
        "unaffected Robot was affected",
    )

    interrupted.runtime.shutdown()
    replacement = _start_agent(config, interrupted.robot_id, interrupted.name)
    failed = _wait_for(
        "crashed execution FAILED",
        lambda: _execution_status(http, session_a, execution_a),
        lambda value: value.get("status") == "FAILED",
        config,
    )
    _assert(failed.get("status") == "FAILED", "crashed execution was not reconciled")
    _assert(
        _find_robot(http, interrupted.robot_id).get("occupied") is False,
        "interrupted Robot was not released",
    )
    _assert(
        _find_robot(http, unaffected.robot_id).get("occupied") is False,
        "unaffected Robot release was affected",
    )
    _assert(replacement.runtime.active_execution_id is None, "replacement Agent retained active ID")
    _assert(unaffected.runtime.active_execution_id is None, "unaffected Agent retained active ID")
    if interrupted is agent_a:
        return replacement, agent_b
    return agent_a, replacement


def _assert_no_work(agent_a: AgentFixture, agent_b: AgentFixture) -> None:
    _assert(agent_a.runtime.execution_once(GateExecutor()) is None, "A received stale work")
    _assert(agent_b.runtime.execution_once(GateExecutor()) is None, "B received stale work")


def _assert_running(
    http: E2EHttpClient,
    config: E2EConfig,
    session_a: str,
    execution_a: UUID,
    session_b: str,
    execution_b: UUID,
) -> None:
    _wait_for(
        "both executions RUNNING",
        lambda: {
            "a": _execution_status(http, session_a, execution_a),
            "b": _execution_status(http, session_b, execution_b),
        },
        lambda value: (
            value["a"].get("status") == "RUNNING" and value["b"].get("status") == "RUNNING"
        ),
        config,
    )


def _assert_terminal_and_released(
    http: E2EHttpClient,
    config: E2EConfig,
    session_token: str,
    execution_id: UUID,
    robot_id: UUID,
    expected_status: str = "COMPLETED",
) -> None:
    status = _wait_for(
        f"Execution {execution_id} {expected_status}",
        lambda: _execution_status(http, session_token, execution_id),
        lambda value: value.get("status") == expected_status,
        config,
    )
    if expected_status == "COMPLETED":
        _assert(
            status.get("assignedRobotId") == str(robot_id),
            "completed execution Robot identity changed",
        )
    else:
        _assert(
            status.get("assignedRobotId") in {None, str(robot_id)},
            "cancelled execution points to another Robot",
        )
    robot = _wait_for(
        f"Robot {robot_id} release",
        lambda: _find_robot(http, robot_id),
        lambda value: value.get("occupied") is False and value.get("currentExecutionId") is None,
        config,
    )
    _assert(robot.get("currentExecutionId") is None, "Robot retained current execution")


def _assert_credential_isolation(
    config: E2EConfig, agent_a: AgentFixture, agent_b: AgentFixture
) -> None:
    heartbeat = HeartbeatRequest(
        sent_at=datetime.now(UTC),
        robots=(
            HeartbeatRobotRequest(
                robot_id=agent_b.robot_id,
                connection_status="ONLINE",
                operational_status="READY",
                battery_percent=87,
                current_execution_id_provided=False,
            ),
        ),
    ).to_json()
    _expect_agent_rejected(
        config,
        agent_a.runtime_token,
        "POST",
        f"/api/v1/internal/agents/{agent_b.registration.agent_id}/heartbeat",
        heartbeat,
    )
    _expect_agent_rejected(
        config,
        agent_b.runtime_token,
        "GET",
        f"/api/v1/internal/agents/{agent_a.registration.agent_id}/executions/next?robotId={agent_a.robot_id}",
        None,
    )


def _expect_agent_rejected(
    config: E2EConfig,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    headers = {"Accept": "application/json", "X-Agent-Token": token}
    encoded = None
    if payload is not None:
        import json

        headers["Content-Type"] = "application/json"
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(f"{config.server_url}{path}", data=encoded, headers=headers, method=method)
    try:
        with build_opener().open(request, timeout=config.http_timeout_seconds) as response:
            raise FullMockE2EError(f"cross-agent request unexpectedly returned {response.status}")
    except HTTPError as exc:
        exc.read()
        _assert(exc.code in {401, 403}, "cross-agent request was not rejected by auth")
    except URLError as exc:
        raise FullMockE2EError("cross-agent credential probe failed") from exc


def _wait_event(event: Event, config: E2EConfig) -> None:
    if not event.wait(config.timeout_seconds):
        raise FullMockE2EError("concurrent Agent executor did not start")


def _config_from_environment() -> E2EConfig:
    return E2EConfig.from_environment()


def _block_program() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "blocks": [
            {"id": "start-1", "type": "START", "parameters": {}},
            {"id": "wait-1", "type": "WAIT", "parameters": {"durationSeconds": 0.1}},
            {
                "id": "move-1",
                "type": "MOVE_FORWARD",
                "parameters": {"distanceMeters": 0.1},
            },
            {"id": "stop-1", "type": "STOP", "parameters": {}},
            {"id": "end-1", "type": "END", "parameters": {}},
        ],
    }


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FullMockE2EError as exc:
        print(f"TWO AGENT E2E FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
