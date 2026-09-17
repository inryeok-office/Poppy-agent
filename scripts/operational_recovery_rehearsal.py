"""Run the software-only operational recovery rehearsal over local HTTP."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any
from uuid import UUID, uuid4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from full_mock_e2e import (  # noqa: E402
    E2EConfig,
    E2EHttpClient,
    FullMockE2EError,
    _block_program,
    _execution_status,
    _find_robot,
    _required_string,
    _wait_for,
)
from stale_agent_fencing_e2e import (  # noqa: E402
    AgentFixture,
    _assert_old_report_did_not_change_terminal_state,
    _expect_stale_endpoints_rejected,
    _prepare_robot,
    _retire_robot_fixture,
)

from poppy_agent.agent import create_agent  # noqa: E402
from poppy_agent.config import AgentConfig  # noqa: E402
from poppy_agent.execution import (  # noqa: E402
    ExecutionCancellationToken,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTask,
)
from poppy_agent.server import (  # noqa: E402
    AgentServerRuntime,
    ServerApiError,
    ServerClient,
    ServerConfig,
    ServerTransportError,
)


class FaultInjectingServerClient(ServerClient):
    """Use the real HTTP client while allowing a deterministic transport outage."""

    def __init__(self, config: ServerConfig) -> None:
        super().__init__(config)
        self.outage = Event()
        self.failure_seen = Event()

    def _ensure_available(self) -> None:
        if self.outage.is_set():
            self.failure_seen.set()
            raise ServerTransportError("rehearsal transport outage")

    def send_heartbeat(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_available()
        return super().send_heartbeat(*args, **kwargs)

    def fetch_next_execution(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_available()
        return super().fetch_next_execution(*args, **kwargs)

    def get_execution_status(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_available()
        return super().get_execution_status(*args, **kwargs)

    def report_execution_status(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_available()
        return super().report_execution_status(*args, **kwargs)

    def discover_active_execution(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_available()
        return super().discover_active_execution(*args, **kwargs)

    def recover_active_execution(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_available()
        return super().recover_active_execution(*args, **kwargs)


class RehearsalExecutor:
    """Complete the baseline, then hold later executions at a mock boundary."""

    def __init__(self) -> None:
        self.invocation_count = 0
        self.started: dict[int, Event] = {}
        self.baseline_release = Event()

    def execute(
        self,
        task: ExecutionTask,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> ExecutionResult:
        token = cancellation_token or ExecutionCancellationToken()
        self.invocation_count += 1
        invocation = self.invocation_count
        self.started.setdefault(invocation, Event()).set()
        if invocation == 1:
            while not self.baseline_release.wait(0.01):
                if token.is_cancelled():
                    return ExecutionResult(task.execution_id, ExecutionStatus.CANCELLED)
            return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)

        while not token.is_cancelled():
            Event().wait(0.01)
        return ExecutionResult(task.execution_id, ExecutionStatus.CANCELLED)


class CompleteExecutor:
    def execute(
        self,
        task: ExecutionTask,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)


class FailIfCalledExecutor:
    def execute(
        self,
        _task: ExecutionTask,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> ExecutionResult:
        raise FullMockE2EError("recovered execution was replayed")


class EventCaptureHandler(logging.Handler):
    """Capture stable event names without printing secrets or payloads."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.events: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "poppy_event", None)
        if isinstance(event, str):
            self.events.append(event)


@dataclass(slots=True)
class RuntimeFixture:
    agent: AgentFixture
    client: FaultInjectingServerClient
    stop_event: Event
    loop: Thread
    errors: list[BaseException]
    status_path: Path


def main() -> int:
    config = E2EConfig.from_environment()
    if not config.server_url.startswith("http://localhost"):
        raise FullMockE2EError("operational rehearsal only permits http://localhost")

    http = E2EHttpClient(config.server_url, config.http_timeout_seconds, config.agent_token)
    run_id = uuid4().hex
    robot_id: UUID | None = None
    old: RuntimeFixture | None = None
    replacement: RuntimeFixture | None = None
    replacement_candidates: list[RuntimeFixture] = []
    phase_results: list[str] = []
    event_capture = EventCaptureHandler()
    runtime_logger = logging.getLogger("poppy_agent.server.runtime")
    client_logger = logging.getLogger("poppy_agent.server.client")
    runtime_logger.setLevel(logging.DEBUG)
    client_logger.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(event_capture)

    with TemporaryDirectory(prefix="poppy-operational-rehearsal-") as temp_dir:
        try:
            robot_id = _create_robot(http, run_id)
            agent_name = f"operational-rehearsal-agent-{run_id}"
            old = _start_runtime(
                config,
                robot_id,
                agent_name,
                Path(temp_dir) / "old-status.json",
            )
            _prepare_robot(http, old.agent, config)
            phase_results.append(_phase("clean startup", _clean_startup(old, config)))

            executor = RehearsalExecutor()
            _start_loop(old, executor)
            phase_results.append(
                _phase("normal execution", _normal_execution(http, robot_id, executor, config))
            )

            session_2, execution_2 = _create_execution(http)
            _wait_for_assignment_or_running(http, session_2, execution_2, robot_id, config)
            _wait_for(
                "Execution 2 RUNNING",
                lambda: _execution_status(http, session_2, execution_2),
                lambda value: value.get("status") == "RUNNING",
                config,
            )
            _wait_for_event(executor, 2, config)
            phase_results.append(
                _phase(
                    "active connectivity loss",
                    _active_connectivity_loss(old, executor, execution_2, config),
                )
            )
            old.client.outage.clear()
            phase_results.append(
                _phase(
                    "connectivity restoration and reconciliation",
                    _restore_and_reconcile(http, old, session_2, execution_2, robot_id, config),
                )
            )

            session_3, execution_3 = _create_execution(http)
            _wait_for_assignment_or_running(http, session_3, execution_3, robot_id, config)
            _wait_for(
                "Execution 3 RUNNING",
                lambda: _execution_status(http, session_3, execution_3),
                lambda value: value.get("status") == "RUNNING",
                config,
            )
            _wait_for_event(executor, 3, config)
            replacement = _agent_replacement(
                config,
                http,
                old,
                robot_id,
                agent_name,
                execution_3,
                session_3,
                Path(temp_dir) / "replacement-status.json",
                replacement_candidates,
            )
            phase_results.append(_phase("Agent replacement and stale fencing", True))

            phase_results.append(
                _phase(
                    "post-recovery execution",
                    _post_recovery_execution(http, replacement, robot_id, config),
                )
            )
            phase_results.append(
                _phase(
                    "final consistency audit",
                    _final_audit(
                        http,
                        old,
                        replacement,
                        robot_id,
                        session_2,
                        execution_2,
                        session_3,
                        execution_3,
                        config,
                    ),
                )
            )
            _assert_events(event_capture.events)
            print("Operational Recovery Rehearsal PASSED")
            print("Phases: " + ", ".join(phase_results))
            return 0
        except Exception as exc:
            runtime_errors: list[str] = []
            if old is not None:
                runtime_errors.extend(_error_summary(error) for error in old.errors)
            for candidate in replacement_candidates:
                runtime_errors.extend(_error_summary(error) for error in candidate.errors)
            suffix = f"; runtime errors={runtime_errors}" if runtime_errors else ""
            print(f"OPERATIONAL RECOVERY REHEARSAL FAILED: {exc}{suffix}", file=sys.stderr)
            return 1
        finally:
            _reconcile_before_cleanup(old)
            for candidate in replacement_candidates:
                _reconcile_before_cleanup(candidate)
            _cleanup_runtime(old)
            for candidate in replacement_candidates:
                if candidate is not old:
                    _cleanup_runtime(candidate)
            if robot_id is not None:
                _retire_robot_fixture(http, robot_id, config)
            logging.getLogger().removeHandler(event_capture)


def _clean_startup(runtime: RuntimeFixture, config: E2EConfig) -> bool:
    snapshot = _wait_for_snapshot(
        runtime.status_path,
        "clean startup readiness",
        lambda value: (
            value.get("operationalReady") is True
            and value.get("connectivityState") == "CONNECTED"
            and value.get("recoveryComplete") is True
        ),
        config,
    )
    if snapshot.get("activeExecutionId") is not None:
        raise FullMockE2EError("clean startup discovered an active execution")
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _normal_execution(
    http: E2EHttpClient,
    robot_id: UUID,
    executor: RehearsalExecutor,
    config: E2EConfig,
) -> bool:
    session, execution = _create_execution(http)
    _wait_for_assignment_or_running(http, session, execution, robot_id, config)
    _wait_for(
        "baseline Execution RUNNING",
        lambda: _execution_status(http, session, execution),
        lambda value: value.get("status") == "RUNNING",
        config,
    )
    executor.baseline_release.set()
    _wait_for(
        "baseline Execution COMPLETED",
        lambda: _execution_status(http, session, execution),
        lambda value: value.get("status") == "COMPLETED",
        config,
    )
    _wait_for_robot_release(http, robot_id, config)
    return True


def _active_connectivity_loss(
    runtime: RuntimeFixture,
    executor: RehearsalExecutor,
    execution_id: UUID,
    config: E2EConfig,
) -> bool:
    previous_dispatches = executor.invocation_count
    runtime.client.outage.set()
    _wait_for(
        "runtime attempted a transport call during outage",
        lambda: {"seen": runtime.client.failure_seen.is_set()},
        lambda value: value.get("seen") is True,
        config,
    )
    degraded = _wait_for_snapshot(
        runtime.status_path,
        "runtime DEGRADED during transport outage",
        lambda value: (
            value.get("connectivityState") == "DEGRADED"
            and value.get("operationalReady") is False
            and value.get("acceptingNewExecution") is False
            and value.get("activeExecutionId") == str(execution_id)
        ),
        config,
    )
    before_server_success = degraded.get("lastServerSuccessAt")
    before_heartbeat_success = degraded.get("lastHeartbeatSuccessAt")
    Event().wait(min(0.2, config.timeout_seconds))
    steady = _read_snapshot(runtime.status_path)
    if steady.get("lastServerSuccessAt") != before_server_success:
        raise FullMockE2EError("failed Server request refreshed lastServerSuccessAt")
    if steady.get("lastHeartbeatSuccessAt") != before_heartbeat_success:
        raise FullMockE2EError("failed heartbeat refreshed lastHeartbeatSuccessAt")
    if executor.invocation_count != previous_dispatches:
        raise FullMockE2EError("transport outage allowed another executor invocation")
    _assert_snapshot_safe(degraded, runtime.agent.runtime_token)
    return True


def _restore_and_reconcile(
    http: E2EHttpClient,
    runtime: RuntimeFixture,
    session: str,
    execution_id: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> bool:
    _wait_for(
        "interrupted Execution FAILED after reconnect",
        lambda: _execution_status(http, session, execution_id),
        lambda value: value.get("status") == "FAILED",
        config,
    )
    _wait_for_robot_release(http, robot_id, config)
    snapshot = _wait_for_snapshot(
        runtime.status_path,
        "runtime READY after reconciliation",
        lambda value: (
            value.get("operationalReady") is True
            and value.get("connectivityState") == "CONNECTED"
            and value.get("activeExecutionId") is None
            and value.get("acceptingNewExecution") is True
        ),
        config,
    )
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _agent_replacement(
    config: E2EConfig,
    http: E2EHttpClient,
    old: RuntimeFixture,
    robot_id: UUID,
    agent_name: str,
    execution_id: UUID,
    session: str,
    status_path: Path,
    replacement_candidates: list[RuntimeFixture],
) -> RuntimeFixture:
    replacement = _start_runtime(config, robot_id, agent_name, status_path)
    replacement_candidates.append(replacement)
    if replacement.agent.registration.agent_id != old.agent.registration.agent_id:
        raise FullMockE2EError("replacement Agent received a different agentId")
    if replacement.agent.runtime_token == old.agent.runtime_token:
        raise FullMockE2EError("replacement Agent did not rotate its runtime credential")

    _wait_for(
        "Execution 3 FAILED after Agent replacement",
        lambda: _execution_status(http, session, execution_id),
        lambda value: value.get("status") == "FAILED",
        config,
    )
    _wait_for_robot_release(http, robot_id, config)
    _expect_stale_endpoints_rejected(config, old.agent, execution_id)
    _assert_old_report_did_not_change_terminal_state(http, session, execution_id)
    _wait_for_snapshot(
        replacement.status_path,
        "replacement Agent READY",
        lambda value: (
            value.get("operationalReady") is True
            and value.get("connectivityState") == "CONNECTED"
            and value.get("recoveryComplete") is True
        ),
        config,
    )
    if replacement.agent.runtime.execution_once(FailIfCalledExecutor()) is not None:
        raise FullMockE2EError("replacement Agent replayed the recovered Execution")
    if old.loop.is_alive():
        raise FullMockE2EError("stale Agent runtime continued after credential fencing")
    if old.errors == []:
        raise FullMockE2EError("stale Agent runtime did not stop after authentication failure")
    return replacement


def _post_recovery_execution(
    http: E2EHttpClient,
    runtime: RuntimeFixture | None,
    robot_id: UUID,
    config: E2EConfig,
) -> bool:
    if runtime is None:
        raise FullMockE2EError("replacement Agent was not available")
    runtime.agent.runtime.heartbeat_once()
    session, execution = _create_execution(http)
    _wait_for_assignment(http, session, execution, robot_id, config)
    result = runtime.agent.runtime.execution_once(CompleteExecutor())
    if result is None or result.status is not ExecutionStatus.COMPLETED:
        raise FullMockE2EError("replacement Agent could not process post-recovery work")
    _wait_for(
        "post-recovery Execution COMPLETED",
        lambda: _execution_status(http, session, execution),
        lambda value: value.get("status") == "COMPLETED",
        config,
    )
    _wait_for_robot_release(http, robot_id, config)
    snapshot = _wait_for_snapshot(
        runtime.status_path,
        "post-recovery accepting state",
        lambda value: (
            value.get("operationalReady") is True
            and value.get("acceptingNewExecution") is True
            and value.get("activeExecutionId") is None
        ),
        config,
    )
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _final_audit(
    http: E2EHttpClient,
    old: RuntimeFixture,
    replacement: RuntimeFixture | None,
    robot_id: UUID,
    session_2: str,
    execution_2: UUID,
    session_3: str,
    execution_3: UUID,
    config: E2EConfig,
) -> bool:
    if replacement is None:
        raise FullMockE2EError("final audit has no replacement Agent")
    _wait_for_snapshot(
        replacement.status_path,
        "final operational readiness",
        lambda value: (
            value.get("lifecycleState") == "READY"
            and value.get("connectivityState") == "CONNECTED"
            and value.get("operationalReady") is True
            and value.get("acceptingNewExecution") is True
            and value.get("activeExecutionId") is None
        ),
        config,
    )
    robot = _find_robot(http, robot_id)
    if robot.get("connectionStatus") != "ONLINE" or robot.get("operationalStatus") != "READY":
        raise FullMockE2EError("final Robot status is not ONLINE/READY")
    if robot.get("occupied") is not False or robot.get("currentExecutionId") is not None:
        raise FullMockE2EError("final Robot ownership is not released")
    if _execution_status(http, session_2, execution_2).get("status") != "FAILED":
        raise FullMockE2EError("network-interrupted Execution changed after recovery")
    if _execution_status(http, session_3, execution_3).get("status") != "FAILED":
        raise FullMockE2EError("restart-interrupted Execution changed after recovery")
    if old.agent.runtime_token == replacement.agent.runtime_token:
        raise FullMockE2EError("old and replacement credentials unexpectedly match")
    return True


def _start_runtime(
    config: E2EConfig,
    robot_id: UUID,
    agent_name: str,
    status_path: Path,
) -> RuntimeFixture:
    server_config = ServerConfig(
        server_url=config.server_url,
        agent_token=config.agent_token,
        agent_name=agent_name,
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="operational-recovery-rehearsal",
        heartbeat_interval_seconds=5.0,
        execution_poll_interval_seconds=config.poll_interval_seconds,
        connect_timeout_seconds=config.http_timeout_seconds,
        read_timeout_seconds=config.http_timeout_seconds,
        max_retries=0,
        reconnect_initial_delay_seconds=0.05,
        reconnect_max_delay_seconds=0.2,
        runtime_status_path=str(status_path),
    )
    client = FaultInjectingServerClient(server_config)
    runtime = AgentServerRuntime(
        create_agent(AgentConfig(robot_mode="mock", robot_id=str(robot_id))),
        client,
        server_config,
    )
    try:
        registration = runtime.start()
    except ServerApiError as exc:
        raise FullMockE2EError(f"Agent {agent_name} startup API failure: {exc}") from exc
    if robot_id not in registration.accepted_robot_ids:
        raise FullMockE2EError("Agent did not accept its Robot")
    token = registration.agent_token
    if token is None or not token.strip():
        raise FullMockE2EError("Server did not issue a runtime credential")
    fixture = AgentFixture(agent_name, robot_id, runtime, registration, token)
    stop_event = Event()
    return RuntimeFixture(fixture, client, stop_event, Thread(), [], status_path)


def _start_loop(runtime: RuntimeFixture, executor: RehearsalExecutor) -> None:
    runtime.loop = Thread(
        target=_run_loop,
        args=(runtime, executor),
        name="operational-recovery-runtime",
        daemon=True,
    )
    runtime.loop.start()


def _run_loop(runtime: RuntimeFixture, executor: RehearsalExecutor) -> None:
    try:
        runtime.agent.runtime.run_loop(runtime.stop_event, executor)
    except BaseException as exc:
        runtime.errors.append(exc)


def _cleanup_runtime(runtime: RuntimeFixture | None) -> None:
    if runtime is None:
        return
    runtime.stop_event.set()
    if runtime.loop.is_alive():
        runtime.loop.join(timeout=5.0)
    runtime.agent.runtime.shutdown()


def _reconcile_before_cleanup(runtime: RuntimeFixture | None) -> None:
    if runtime is None or runtime.agent.runtime.agent_id is None:
        return
    runtime.client.outage.clear()
    runtime.stop_event.set()
    if runtime.loop.is_alive():
        runtime.loop.join(timeout=5.0)
    try:
        runtime.agent.runtime.recover_interrupted_execution()
    except Exception:
        return


def _error_summary(error: BaseException) -> str:
    if isinstance(error, ServerApiError):
        return f"ServerApiError(status={error.status_code},code={error.error_code})"
    return type(error).__name__


def _create_robot(http: E2EHttpClient, run_id: str) -> UUID:
    data = http.post(
        "/api/v1/admin/robots",
        {
            "alias": f"operational-rehearsal-{run_id}",
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
    block_version = revision.get("blockVersion")
    if not isinstance(block_version, int):
        raise FullMockE2EError("block revision version is malformed")
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
    session: str,
    execution_id: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> None:
    _wait_for(
        f"Execution {execution_id} ASSIGNED",
        lambda: _execution_status(http, session, execution_id),
        lambda value: (
            value.get("status") == "ASSIGNED" and value.get("assignedRobotId") == str(robot_id)
        ),
        config,
    )


def _wait_for_assignment_or_running(
    http: E2EHttpClient,
    session: str,
    execution_id: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> None:
    _wait_for(
        f"Execution {execution_id} assigned to expected Robot",
        lambda: _execution_status(http, session, execution_id),
        lambda value: (
            value.get("status") in {"ASSIGNED", "RUNNING"}
            and value.get("assignedRobotId") == str(robot_id)
        ),
        config,
    )


def _wait_for_event(executor: RehearsalExecutor, invocation: int, config: E2EConfig) -> None:
    _wait_for(
        f"executor invocation {invocation}",
        lambda: {"started": executor.started.get(invocation, Event()).is_set()},
        lambda value: value.get("started") is True,
        config,
    )


def _wait_for_robot_release(http: E2EHttpClient, robot_id: UUID, config: E2EConfig) -> None:
    _wait_for(
        f"Robot {robot_id} release",
        lambda: _find_robot(http, robot_id),
        lambda value: value.get("occupied") is False and value.get("currentExecutionId") is None,
        config,
    )


def _read_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _wait_for_snapshot(
    path: Path,
    description: str,
    predicate: Callable[[dict[str, Any]], bool],
    config: E2EConfig,
) -> dict[str, Any]:
    return _wait_for(description, lambda: _read_snapshot(path), predicate, config)


def _assert_snapshot_safe(snapshot: dict[str, Any], runtime_token: str) -> None:
    serialized = json.dumps(snapshot, ensure_ascii=False)
    for forbidden in (
        runtime_token,
        "X-Agent-Token",
        "Authorization",
        "commandPayload",
        "sessionToken",
        "recoveryCode",
    ):
        if forbidden and forbidden in serialized:
            raise FullMockE2EError("operational snapshot contains a forbidden secret field")


def _phase(name: str, passed: bool) -> str:
    if not passed:
        raise FullMockE2EError(f"phase failed: {name}")
    print(f"{name}: PASS")
    return name


def _assert_events(events: list[str]) -> None:
    required = {
        "server_connectivity_lost",
        "runtime_degraded",
        "execution_interrupted_by_transport",
        "server_connectivity_restored",
        "runtime_resumed",
        "execution_reconciliation_started",
        "execution_reconciliation_completed",
        "authentication_failure",
    }
    missing = sorted(required.difference(events))
    if missing:
        raise FullMockE2EError(f"structured event regression: missing {', '.join(missing)}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FullMockE2EError, OSError, RuntimeError) as exc:
        print(f"OPERATIONAL RECOVERY REHEARSAL FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
