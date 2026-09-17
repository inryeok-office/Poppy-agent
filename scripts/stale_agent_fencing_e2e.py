"""Verify stale Agent credential fencing and active-execution handoff over HTTP."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep
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
    _block_program,
    _execution_status,
    _find_robot,
    _required_int,
    _required_string,
    _wait_for,
)
from rehearsal_safety import is_allowed_loopback_server_url  # noqa: E402

from poppy_agent.agent import create_agent  # noqa: E402
from poppy_agent.config import AgentConfig  # noqa: E402
from poppy_agent.execution import ExecutionResult, ExecutionStatus  # noqa: E402
from poppy_agent.server import (  # noqa: E402
    AgentRegistrationResponse,
    AgentServerRuntime,
    HeartbeatRequest,
    HeartbeatRobotRequest,
    ServerClient,
    ServerConfig,
)


@dataclass(slots=True)
class AgentFixture:
    name: str
    robot_id: UUID
    runtime: AgentServerRuntime
    registration: AgentRegistrationResponse
    runtime_token: str


class FencingAwareExecutor:
    """Record mock dispatch ticks and stop cooperatively after stale fencing."""

    def __init__(self, timeout_seconds: float) -> None:
        self.started = Event()
        self.abort = Event()
        self.timeout_seconds = timeout_seconds
        self.dispatch_count = 0

    def execute(self, task: Any, *, cancellation_token: Any) -> ExecutionResult:
        self.started.set()
        deadline = monotonic() + self.timeout_seconds
        while not cancellation_token.is_cancelled():
            if self.abort.wait(0.01):
                raise RuntimeError("stale Agent cancellation was not delivered")
            self.dispatch_count += 1
            if monotonic() >= deadline:
                raise RuntimeError("stale Agent fencing timeout")
        return ExecutionResult(task.execution_id, ExecutionStatus.CANCELLED)


class FailIfCalledExecutor:
    def execute(self, _task: Any) -> ExecutionResult:
        raise FullMockE2EError("recovered execution was replayed by the new Agent")


class CompleteExecutor:
    def execute(self, task: Any) -> ExecutionResult:
        return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)


def main() -> int:
    config = E2EConfig.from_environment()
    if not is_allowed_loopback_server_url(config.server_url):
        raise FullMockE2EError("stale Agent E2E only permits http://localhost")
    http = E2EHttpClient(config.server_url, config.http_timeout_seconds, config.agent_token)
    run_id = uuid4().hex
    _run_idle_fencing(http, config, run_id)
    print("Idle stale credential fencing confirmed for all Agent endpoints")
    _run_active_handoff(http, config, run_id)
    print("RUNNING handoff confirmed: stale executor stopped, recovery replay=0")
    print("STALE AGENT FENCING E2E PASSED")
    return 0


def _run_idle_fencing(http: E2EHttpClient, config: E2EConfig, run_id: str) -> None:
    robot_id = _create_robot(http, f"stale-idle-{run_id}")
    agent_name = f"stale-idle-agent-{run_id}"
    old = _start_agent(config, robot_id, agent_name)
    new: AgentFixture | None = None
    try:
        _prepare_robot(http, old, config)
        new = _start_agent(config, robot_id, agent_name)
        _assert_same_identity_with_rotated_credential(old, new)
        _expect_stale_endpoints_rejected(
            config,
            old,
            execution_id=uuid4(),
        )
        new.runtime.heartbeat_once()
        delivery = new.runtime.server.fetch_next_execution(new.registration.agent_id, robot_id)
        if delivery is not None:
            raise FullMockE2EError("new Agent unexpectedly received idle work")
        _assert_same_robot_different_agent_rejected(http, config, robot_id, run_id)
    finally:
        try:
            try:
                old.runtime.shutdown()
            finally:
                if new is not None:
                    new.runtime.shutdown()
        finally:
            _retire_robot_fixture(http, robot_id, config)


def _run_active_handoff(http: E2EHttpClient, config: E2EConfig, run_id: str) -> None:
    robot_id = _create_robot(http, f"stale-active-{run_id}")
    agent_name = f"stale-active-agent-{run_id}"
    old = _start_agent(config, robot_id, agent_name)
    new: AgentFixture | None = None
    errors: list[BaseException] = []
    executor = FencingAwareExecutor(config.timeout_seconds)
    try:
        _prepare_robot(http, old, config)
        session_token, execution_id = _create_execution(http)
        _wait_for_assignment(http, session_token, execution_id, robot_id, config)

        def run_old_execution() -> None:
            try:
                old.runtime.execution_once(executor)
            except BaseException as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale-agent-e2e") as pool:
            old_future = pool.submit(run_old_execution)
            try:
                _wait_event(executor.started, config)
                _wait_for(
                    "old execution RUNNING",
                    lambda: _execution_status(http, session_token, execution_id),
                    lambda value: value.get("status") == "RUNNING",
                    config,
                )

                new = _start_agent(config, robot_id, agent_name)
                _assert_same_identity_with_rotated_credential(old, new)
                recovered = _wait_for(
                    "stale execution FAILED",
                    lambda: _execution_status(http, session_token, execution_id),
                    lambda value: value.get("status") == "FAILED",
                    config,
                )
                if recovered.get("status") != "FAILED":
                    raise FullMockE2EError("stale execution was not reconciled as FAILED")

                _expect_stale_endpoints_rejected(config, old, execution_id)
                _assert_old_report_did_not_change_terminal_state(http, session_token, execution_id)
                try:
                    old_future.result(timeout=config.timeout_seconds)
                except TimeoutError as exc:
                    raise FullMockE2EError(
                        "stale Agent execution did not terminate after fencing"
                    ) from exc
                except BaseException:
                    pass
            finally:
                executor.abort.set()

        if not errors:
            raise FullMockE2EError("stale execution did not terminate with an auth failure")
        if executor.dispatch_count == 0:
            raise FullMockE2EError("old executor did not reach the mock dispatch boundary")
        dispatched = executor.dispatch_count
        sleep(0.05)
        if executor.dispatch_count != dispatched:
            raise FullMockE2EError("old executor dispatched after credential fencing")
        if new is None:
            raise FullMockE2EError("replacement Agent was not started")
        released = _wait_for(
            "Robot release after stale recovery",
            lambda: _find_robot(http, robot_id),
            lambda value: (
                value.get("occupied") is False and value.get("currentExecutionId") is None
            ),
            config,
        )
        if released.get("currentExecutionId") is not None:
            raise FullMockE2EError("Robot retained stale execution ownership")
        if new.runtime.execution_once(FailIfCalledExecutor()) is not None:
            raise FullMockE2EError("new Agent received replayed stale execution")

        next_session, next_execution = _create_execution(http)
        _wait_for_assignment(http, next_session, next_execution, robot_id, config)
        result = new.runtime.execution_once(CompleteExecutor())
        if result is None or result.status is not ExecutionStatus.COMPLETED:
            raise FullMockE2EError("new Agent could not process a new execution")
    finally:
        executor.abort.set()
        try:
            try:
                old.runtime.shutdown()
            finally:
                if new is not None:
                    new.runtime.shutdown()
        finally:
            _retire_robot_fixture(http, robot_id, config)


def _start_agent(config: E2EConfig, robot_id: UUID, name: str) -> AgentFixture:
    server_config = ServerConfig(
        server_url=config.server_url,
        agent_token=config.agent_token,
        agent_name=name,
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="stale-agent-e2e",
        heartbeat_interval_seconds=30.0,
        execution_poll_interval_seconds=config.poll_interval_seconds,
        connect_timeout_seconds=config.http_timeout_seconds,
        read_timeout_seconds=config.http_timeout_seconds,
        max_retries=0,
    )
    runtime = AgentServerRuntime(
        create_agent(AgentConfig(robot_mode="mock", robot_id=str(robot_id))),
        ServerClient(server_config),
        server_config,
    )
    registration = runtime.start()
    if robot_id not in registration.accepted_robot_ids:
        raise FullMockE2EError("Agent did not accept its Robot")
    token = registration.agent_token
    if token is None or not token.strip():
        raise FullMockE2EError("Server did not issue a runtime credential")
    return AgentFixture(name, robot_id, runtime, registration, token)


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


def _prepare_robot(http: E2EHttpClient, agent: AgentFixture, config: E2EConfig) -> None:
    capabilities = [{"code": "telemetry", "status": "UNVERIFIED"}]
    capabilities.extend(
        {"code": code, "status": "VERIFIED"} for code in sorted(COMMAND_CAPABILITIES)
    )
    http.patch(f"/api/v1/admin/robots/{agent.robot_id}", {"capabilities": capabilities})
    agent.runtime.heartbeat_once()
    _wait_for(
        f"Robot {agent.robot_id} ready",
        lambda: _find_robot(http, agent.robot_id),
        lambda value: (
            value.get("connectionStatus") == "ONLINE"
            and value.get("operationalStatus") == "READY"
            and value.get("occupied") is False
        ),
        config,
    )


def _retire_robot_fixture(http: E2EHttpClient, robot_id: UUID, config: E2EConfig) -> None:
    """Remove a completed scenario Robot from the next allocation pool."""
    http.patch(
        f"/api/v1/admin/robots/{robot_id}",
        {"operationalStatus": "UNAVAILABLE"},
    )
    retired = _wait_for(
        f"Robot {robot_id} retired",
        lambda: _find_robot(http, robot_id),
        lambda value: (
            value.get("operationalStatus") == "UNAVAILABLE"
            and value.get("occupied") is False
            and value.get("currentExecutionId") is None
        ),
        config,
    )
    if retired.get("operationalStatus") != "UNAVAILABLE":
        raise FullMockE2EError(f"Robot {robot_id} remained allocation-eligible")


def _create_execution(http: E2EHttpClient) -> tuple[str, UUID]:
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
    return session_token, UUID(_required_string(execution, "executionId"))


def _wait_for_assignment(
    http: E2EHttpClient,
    session_token: str,
    execution_id: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> None:
    _wait_for(
        f"Execution {execution_id} ASSIGNED",
        lambda: _execution_status(http, session_token, execution_id),
        lambda value: (
            value.get("status") == "ASSIGNED" and value.get("assignedRobotId") == str(robot_id)
        ),
        config,
    )


def _assert_same_identity_with_rotated_credential(old: AgentFixture, new: AgentFixture) -> None:
    if old.registration.agent_id != new.registration.agent_id:
        raise FullMockE2EError("same logical Agent received a different agentId")
    if old.runtime_token == new.runtime_token:
        raise FullMockE2EError("runtime credential was not rotated")


def _expect_stale_endpoints_rejected(
    config: E2EConfig, old: AgentFixture, execution_id: UUID
) -> None:
    agent_id = old.registration.agent_id
    robot_id = old.robot_id
    heartbeat = HeartbeatRequest(
        sent_at=datetime.now(UTC),
        robots=(
            HeartbeatRobotRequest(
                robot_id=robot_id,
                connection_status="ONLINE",
                operational_status="READY",
                battery_percent=90,
                current_execution_id_provided=False,
            ),
        ),
    ).to_json()
    _expect_rejected(
        config,
        old.runtime_token,
        "POST",
        f"/api/v1/internal/agents/{agent_id}/heartbeat",
        heartbeat,
    )
    _expect_rejected(
        config,
        old.runtime_token,
        "GET",
        f"/api/v1/internal/agents/{agent_id}/executions/next?robotId={robot_id}",
        None,
    )
    _expect_rejected(
        config,
        old.runtime_token,
        "GET",
        f"/api/v1/internal/agents/{agent_id}/executions/{execution_id}/status?robotId={robot_id}",
        None,
    )
    _expect_rejected(
        config,
        old.runtime_token,
        "POST",
        f"/api/v1/internal/agents/{agent_id}/executions/{execution_id}/status",
        {"robotId": str(robot_id), "status": "COMPLETED"},
    )
    _expect_rejected(
        config,
        old.runtime_token,
        "GET",
        f"/api/v1/internal/agents/{agent_id}/robots/{robot_id}/active-execution",
        None,
    )
    _expect_rejected(
        config,
        old.runtime_token,
        "POST",
        f"/api/v1/internal/agents/{agent_id}/robots/{robot_id}/active-execution/recover",
        {},
    )


def _assert_old_report_did_not_change_terminal_state(
    http: E2EHttpClient, session_token: str, execution_id: UUID
) -> None:
    status = _execution_status(http, session_token, execution_id)
    if status.get("status") != "FAILED":
        raise FullMockE2EError("stale terminal report changed the recovered state")


def _assert_same_robot_different_agent_rejected(
    http: E2EHttpClient, config: E2EConfig, robot_id: UUID, run_id: str
) -> None:
    body = {
        "agentName": f"different-agent-{run_id}",
        "agentVersion": "0.1.0",
        "sdkVersion": "not-applicable",
        "platform": "stale-agent-e2e",
        "robots": [
            {
                "robotId": str(robot_id),
                "model": "mock",
                "edition": "development",
                "firmwareVersion": "mock",
                "capabilities": sorted(COMMAND_CAPABILITIES),
            }
        ],
    }
    _expect_rejected(
        config,
        config.agent_token,
        "POST",
        "/api/v1/internal/agents/register",
        body,
        {409},
    )


def _expect_rejected(
    config: E2EConfig,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    expected_statuses: set[int] | None = None,
) -> None:
    expected = expected_statuses or {401, 403}
    headers = {"Accept": "application/json", "X-Agent-Token": token}
    encoded = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(f"{config.server_url}{path}", data=encoded, headers=headers, method=method)
    try:
        with build_opener().open(request, timeout=config.http_timeout_seconds) as response:
            raise FullMockE2EError(f"stale request unexpectedly returned {response.status}")
    except HTTPError as exc:
        exc.read()
        if exc.code not in expected:
            raise FullMockE2EError(f"stale request returned unexpected HTTP {exc.code}") from exc
    except URLError as exc:
        raise FullMockE2EError("stale request could not reach local Server") from exc


def _wait_event(event: Event, config: E2EConfig) -> None:
    if not event.wait(config.timeout_seconds):
        raise FullMockE2EError("stale Agent executor did not start")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FullMockE2EError as exc:
        print(f"STALE AGENT FENCING E2E FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
