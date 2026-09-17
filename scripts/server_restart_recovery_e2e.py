"""Verify Agent fail-closed behavior across a real Server process restart.

The harness owns only the Spring Boot process it starts. PostgreSQL is an
external prerequisite and is never reset or modified directly.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT / "src", ROOT / "scripts"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from full_mock_e2e import (  # noqa: E402
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
from operational_recovery_rehearsal import (  # noqa: E402
    RehearsalExecutor,
    RuntimeFixture,
    _assert_snapshot_safe,
    _cleanup_runtime,
    _phase,
    _read_snapshot,
    _start_loop,
    _start_runtime,
    _wait_for_assignment_or_running,
    _wait_for_event,
    _wait_for_robot_release,
    _wait_for_snapshot,
)
from rehearsal_cleanup import run_cleanup_steps  # noqa: E402
from rehearsal_safety import is_allowed_loopback_server_url  # noqa: E402
from stale_agent_fencing_e2e import _prepare_robot, _retire_robot_fixture  # noqa: E402


class ServerRestartRehearsalError(RuntimeError):
    """Raised when the process-restart rehearsal cannot satisfy its contract."""


@dataclass(frozen=True, slots=True)
class SessionFixture:
    session_id: str
    session_token: str
    block_version: int


class RestartExecutor(RehearsalExecutor):
    """Count mock execution dispatches while reusing the existing gate fixture."""

    def __init__(self) -> None:
        super().__init__()
        self.command_dispatch_count = 0

    def execute(self, task: Any, cancellation_token: Any = None) -> Any:
        self.command_dispatch_count += 1
        return super().execute(task, cancellation_token=cancellation_token)


class OwnedServerProcess:
    """Start, stop, and restart exactly one explicitly owned Server process."""

    def __init__(self, command: list[str], server_url: str, environment: dict[str, str]) -> None:
        if not command:
            raise ServerRestartRehearsalError("Server restart command is empty")
        self.command = command
        self.server_url = server_url.rstrip("/")
        self.environment = environment
        self.process: subprocess.Popen[bytes] | None = None
        self._owned_tree_pids: set[int] = set()

    def start(self, timeout_seconds: float) -> None:
        if self.process is not None and self.process.poll() is None:
            raise ServerRestartRehearsalError("owned Server process is already running")
        if _server_is_reachable(self.server_url):
            raise ServerRestartRehearsalError(
                "refusing to start: the configured localhost Server port is already in use"
            )
        self.process = subprocess.Popen(
            self.command,
            cwd=str(ROOT),
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_until_ready(timeout_seconds)
        self._owned_tree_pids = _windows_process_tree(self.process.pid)

    def stop(self, timeout_seconds: float) -> None:
        process = self.process
        if process is None:
            return
        pid = process.pid
        self._owned_tree_pids.update(_windows_process_tree(pid))
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout_seconds)
        if _server_is_reachable(self.server_url):
            # A direct java child should exit above. On Windows, terminate the
            # owned process tree only when a descendant still owns the port.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
                for child_pid in sorted(self._owned_tree_pids - {pid}, reverse=True):
                    subprocess.run(
                        ["taskkill", "/PID", str(child_pid), "/F"],
                        capture_output=True,
                        check=False,
                    )
            elif process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                raise ServerRestartRehearsalError(
                    "owned Server process did not terminate"
                ) from None
        self._wait_until_unreachable(timeout_seconds)
        self.process = None
        self._owned_tree_pids.clear()

    def restart(self, timeout_seconds: float) -> None:
        self.stop(timeout_seconds)
        self.start(timeout_seconds)

    def _wait_until_ready(self, timeout_seconds: float) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise ServerRestartRehearsalError("owned Server process exited before readiness")
            if _server_is_reachable(self.server_url):
                return
            sleep(0.1)
        raise ServerRestartRehearsalError("Server process did not become reachable")

    def _wait_until_unreachable(self, timeout_seconds: float) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if not _server_is_reachable(self.server_url):
                return
            sleep(0.05)
        raise ServerRestartRehearsalError("Server remained reachable after owned process stop")


def main() -> int:
    _validate_environment()
    config = E2EConfig.from_environment()
    server = _owned_server_from_environment(config)
    http = E2EHttpClient(config.server_url, config.http_timeout_seconds, config.agent_token)
    robot_id: UUID | None = None
    runtime: RuntimeFixture | None = None
    primary_error: BaseException | None = None
    exit_code = 1

    with TemporaryDirectory(prefix="poppy-server-restart-") as temp_dir:
        try:
            server.start(config.timeout_seconds)
            robot_id = _create_robot(http, uuid4().hex)
            runtime = _start_runtime(
                config,
                robot_id,
                f"server-restart-agent-{uuid4().hex}",
                Path(temp_dir) / "status.json",
            )
            _prepare_robot(http, runtime.agent, config)
            executor = RestartExecutor()
            _start_loop(runtime, executor)
            _phase("clean startup", _assert_clean_startup(runtime, config))

            session = _create_session_fixture(http)
            baseline = _create_execution(http, session)
            _wait_for_assignment_or_running(http, session.session_token, baseline, robot_id, config)
            _wait_for(
                "baseline Execution RUNNING",
                lambda: _execution_status(http, session.session_token, baseline),
                lambda value: value.get("status") == "RUNNING",
                config,
            )
            _wait_for_event(executor, 1, config)
            executor.baseline_release.set()
            _wait_for(
                "baseline Execution COMPLETED",
                lambda: _execution_status(http, session.session_token, baseline),
                lambda value: value.get("status") == "COMPLETED",
                config,
            )
            _wait_for_robot_release(http, robot_id, config)
            _phase("normal Execution", True)

            interrupted = _create_execution(http, session)
            _wait_for_assignment_or_running(
                http, session.session_token, interrupted, robot_id, config
            )
            _wait_for(
                "interrupted Execution RUNNING",
                lambda: _execution_status(http, session.session_token, interrupted),
                lambda value: value.get("status") == "RUNNING",
                config,
            )
            _wait_for_event(executor, 2, config)
            dispatches_before_outage = executor.command_dispatch_count
            snapshot_before_outage = _read_snapshot(runtime.status_path)

            server.stop(config.timeout_seconds)
            _phase(
                "Server process stop and Agent fail-closed",
                _assert_outage(
                    runtime,
                    executor,
                    interrupted,
                    dispatches_before_outage,
                    snapshot_before_outage,
                    config,
                ),
            )

            server.start(config.timeout_seconds)
            _phase(
                "Server process restart and reconciliation",
                _assert_recovery(http, runtime, session, interrupted, robot_id, config),
            )
            _phase(
                "Post-recovery persistent Session execution",
                _post_recovery_execution(http, runtime, session, robot_id, config),
            )
            _phase(
                "Final consistency audit",
                _final_audit(http, runtime, session, baseline, interrupted, robot_id, config),
            )
            print("SERVER RESTART RECOVERY E2E PASSED")
            exit_code = 0
        except BaseException as exc:
            primary_error = exc
            print(
                f"SERVER RESTART RECOVERY E2E FAILED: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        finally:
            cleanup_steps: list[tuple[str, Any]] = []
            if runtime is not None:
                cleanup_steps.append(("Agent runtime shutdown", lambda: _cleanup_runtime(runtime)))
            cleanup_steps.append(
                ("owned Server process restore", lambda: _ensure_server(server, config))
            )
            if robot_id is not None:
                cleanup_steps.append(
                    (
                        "Robot fixture retirement",
                        lambda: _retire_robot_fixture(http, robot_id, config),
                    )
                )
            cleanup_steps.append(("owned Server process stop", lambda: server.stop(10.0)))
            cleanup_failures = run_cleanup_steps(cleanup_steps)
            if cleanup_failures:
                print(
                    "SERVER RESTART RECOVERY CLEANUP WARNINGS: " + ", ".join(cleanup_failures),
                    file=sys.stderr,
                )
                if primary_error is None:
                    exit_code = 1
    return exit_code


def _validate_environment() -> None:
    if os.environ.get("POPPY_SERVER_RESTART_REHEARSAL") != "1":
        raise ServerRestartRehearsalError(
            "POPPY_SERVER_RESTART_REHEARSAL=1 is required for process control"
        )
    if os.environ.get("ROBOT_MODE", "mock").strip().lower() != "mock":
        raise ServerRestartRehearsalError("Server restart rehearsal requires ROBOT_MODE=mock")
    server_url = os.environ.get("POPPY_E2E_SERVER_URL", "").strip()
    if not is_allowed_loopback_server_url(server_url):
        raise ServerRestartRehearsalError("only an HTTP localhost Server target is allowed")
    if not os.environ.get("POPPY_E2E_AGENT_TOKEN", "").strip():
        raise ServerRestartRehearsalError("POPPY_E2E_AGENT_TOKEN is required")
    if not _command_from_environment():
        raise ServerRestartRehearsalError(
            "POPPY_SERVER_RESTART_COMMAND_JSON or POPPY_SERVER_RESTART_COMMAND is required"
        )


def _owned_server_from_environment(config: E2EConfig) -> OwnedServerProcess:
    environment = os.environ.copy()
    environment.update(
        {
            "SPRING_PROFILES_ACTIVE": os.environ.get("POPPY_SERVER_RESTART_PROFILE", "local"),
            "DB_HOST": os.environ.get("POPPY_SERVER_RESTART_DB_HOST", "localhost"),
            "DB_PORT": os.environ.get("POPPY_SERVER_RESTART_DB_PORT", "5432"),
            "DB_NAME": os.environ.get("POPPY_SERVER_RESTART_DB_NAME", "poppy"),
            "DB_USERNAME": os.environ.get("POPPY_SERVER_RESTART_DB_USERNAME", "poppy"),
            "DB_PASSWORD": os.environ.get("POPPY_SERVER_RESTART_DB_PASSWORD", "poppy"),
            "POPPY_AGENT_TOKEN": config.agent_token,
        }
    )
    return OwnedServerProcess(_command_from_environment(), config.server_url, environment)


def _command_from_environment() -> list[str]:
    encoded = os.environ.get("POPPY_SERVER_RESTART_COMMAND_JSON", "").strip()
    if encoded:
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ServerRestartRehearsalError("Server command JSON is malformed") from exc
        if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
            return value
        raise ServerRestartRehearsalError("Server command JSON must be a non-empty string array")
    raw = os.environ.get("POPPY_SERVER_RESTART_COMMAND", "").strip()
    if not raw:
        return []
    return shlex.split(raw, posix=os.name != "nt")


def _server_is_reachable(server_url: str) -> bool:
    parsed = urlsplit(server_url)
    if parsed.hostname is None or parsed.port is None:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=0.25):
            return True
    except OSError:
        return False


def _windows_process_tree(root_pid: int) -> set[int]:
    """Return the owned process tree without inspecting or killing other roots."""

    if os.name != "nt":
        return {root_pid}
    command = (
        "$p = Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        records = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {root_pid}
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return {root_pid}
    parent_by_pid = {
        int(item["ProcessId"]): int(item["ParentProcessId"])
        for item in records
        if isinstance(item, dict)
        and str(item.get("ProcessId", "")).isdigit()
        and str(item.get("ParentProcessId", "")).isdigit()
    }
    tree = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in parent_by_pid.items():
            if parent_pid in tree and pid not in tree:
                tree.add(pid)
                changed = True
    return tree


def _assert_clean_startup(runtime: RuntimeFixture, config: E2EConfig) -> bool:
    snapshot = _wait_for_snapshot(
        runtime.status_path,
        "clean startup readiness",
        lambda value: (
            value.get("lifecycleState") == "READY"
            and value.get("connectivityState") == "CONNECTED"
            and value.get("operationalReady") is True
            and value.get("acceptingNewExecution") is True
            and value.get("activeExecutionId") is None
        ),
        config,
    )
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _assert_outage(
    runtime: RuntimeFixture,
    executor: RestartExecutor,
    execution_id: UUID,
    dispatches_before_outage: int,
    snapshot_before_outage: dict[str, Any],
    config: E2EConfig,
) -> bool:
    snapshot = _wait_for_snapshot(
        runtime.status_path,
        "Agent DEGRADED during Server outage",
        lambda value: (
            value.get("connectivityState") == "DEGRADED"
            and value.get("operationalReady") is False
            and value.get("acceptingNewExecution") is False
            and value.get("activeExecutionId") == str(execution_id)
        ),
        config,
    )
    if runtime.loop.is_alive() is False:
        raise ServerRestartRehearsalError("Agent loop stopped during Server outage")
    if runtime.errors:
        raise ServerRestartRehearsalError("Agent loop failed during transient Server outage")
    # The executor invocation count is the software command-dispatch boundary.
    if executor.command_dispatch_count != dispatches_before_outage:
        raise ServerRestartRehearsalError("Server outage allowed another command dispatch")
    for timestamp_name in ("lastServerSuccessAt", "lastHeartbeatSuccessAt"):
        if snapshot.get(timestamp_name) != snapshot_before_outage.get(timestamp_name):
            raise ServerRestartRehearsalError(f"failed Server request changed {timestamp_name}")
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _ensure_server(server: OwnedServerProcess, config: E2EConfig) -> None:
    if server.process is None or server.process.poll() is not None:
        server.start(config.timeout_seconds)


def _assert_recovery(
    http: E2EHttpClient,
    runtime: RuntimeFixture,
    session: SessionFixture,
    execution_id: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> bool:
    _wait_for(
        "interrupted Execution FAILED after Server restart",
        lambda: _execution_status(http, session.session_token, execution_id),
        lambda value: value.get("status") == "FAILED",
        config,
    )
    _wait_for_robot_release(http, robot_id, config)
    snapshot = _wait_for_snapshot(
        runtime.status_path,
        "Agent READY after Server restart reconciliation",
        lambda value: (
            value.get("lifecycleState") == "READY"
            and value.get("connectivityState") == "CONNECTED"
            and value.get("operationalReady") is True
            and value.get("acceptingNewExecution") is True
            and value.get("activeExecutionId") is None
        ),
        config,
    )
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _post_recovery_execution(
    http: E2EHttpClient,
    runtime: RuntimeFixture,
    session: SessionFixture,
    robot_id: UUID,
    config: E2EConfig,
) -> bool:
    execution_id = _create_execution(http, session)
    _wait_for_assignment_or_running(http, session.session_token, execution_id, robot_id, config)
    result = runtime.agent.runtime.execution_once(_CompleteExecutor())
    if result is None or result.status.value != "COMPLETED":
        raise ServerRestartRehearsalError("post-recovery Execution did not complete")
    _wait_for(
        "post-recovery Execution COMPLETED",
        lambda: _execution_status(http, session.session_token, execution_id),
        lambda value: value.get("status") == "COMPLETED",
        config,
    )
    _wait_for_robot_release(http, robot_id, config)
    return True


class _CompleteExecutor:
    def execute(self, task: Any, cancellation_token: Any = None) -> Any:
        from poppy_agent.execution import ExecutionResult, ExecutionStatus

        return ExecutionResult(task.execution_id, ExecutionStatus.COMPLETED)


def _final_audit(
    http: E2EHttpClient,
    runtime: RuntimeFixture,
    session: SessionFixture,
    baseline: UUID,
    interrupted: UUID,
    robot_id: UUID,
    config: E2EConfig,
) -> bool:
    if _execution_status(http, session.session_token, baseline).get("status") != "COMPLETED":
        raise ServerRestartRehearsalError("baseline Execution changed after restart")
    if _execution_status(http, session.session_token, interrupted).get("status") != "FAILED":
        raise ServerRestartRehearsalError("interrupted Execution is not FAILED")
    robot = _find_robot(http, robot_id)
    if robot.get("occupied") is not False or robot.get("currentExecutionId") is not None:
        raise ServerRestartRehearsalError("Robot ownership was not released")
    snapshot = _read_snapshot(runtime.status_path)
    if snapshot.get("activeExecutionId") is not None:
        raise ServerRestartRehearsalError("Agent retained an active Execution")
    _assert_snapshot_safe(snapshot, runtime.agent.runtime_token)
    return True


def _create_robot(http: E2EHttpClient, run_id: str) -> UUID:
    data = http.post(
        "/api/v1/admin/robots",
        {
            "alias": f"server-restart-{run_id}",
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


def _create_session_fixture(http: E2EHttpClient) -> SessionFixture:
    session = http.post("/api/v1/sessions", {}, expected_status=201)
    session_id = _required_string(session, "sessionId")
    session_token = _required_string(session, "sessionToken")
    revision = http.post(
        f"/api/v1/sessions/{session_id}/block-revisions",
        {"document": _block_program()},
        expected_status=201,
        session_token=session_token,
    )
    return SessionFixture(
        session_id,
        session_token,
        _required_int(revision, "blockVersion"),
    )


def _create_execution(http: E2EHttpClient, session: SessionFixture) -> UUID:
    _record_simulation_pass(http, session)
    execution = http.post(
        f"/api/v1/sessions/{session.session_id}/executions",
        {"blockVersion": session.block_version},
        expected_status=201,
        session_token=session.session_token,
    )
    return UUID(_required_string(execution, "executionId"))


def _record_simulation_pass(http: E2EHttpClient, session: SessionFixture) -> None:
    """Accept the Server's create-or-already-recorded 201/200 contract."""

    try:
        http.post(
            f"/api/v1/sessions/{session.session_id}/simulation-passes",
            {"blockVersion": session.block_version},
            expected_status=201,
            session_token=session.session_token,
        )
    except FullMockE2EError as exc:
        if "returned HTTP 200" not in str(exc):
            raise
        # The 200 response means the idempotent pass already exists. A second
        # read-through request confirms the response shape without changing DB
        # state and keeps this harness compatible with both Server outcomes.
        http.post(
            f"/api/v1/sessions/{session.session_id}/simulation-passes",
            {"blockVersion": session.block_version},
            expected_status=200,
            session_token=session.session_token,
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ServerRestartRehearsalError, FullMockE2EError, OSError, RuntimeError) as exc:
        print(f"SERVER RESTART RECOVERY E2E FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
