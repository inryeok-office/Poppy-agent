"""Run a guarded, software-only systemd recovery rehearsal on Linux."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4


class RehearsalError(RuntimeError):
    """Raised when the guarded systemd rehearsal cannot satisfy a contract."""


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_UNIT = ROOT / "deploy" / "systemd" / "poppy-agent.service"
UNIT_NAME = "poppy-agent-rehearsal.service"
UNIT_PATH = Path("/run/systemd/system") / UNIT_NAME
ENV_PATH = Path("/run/poppy-agent-rehearsal.env")
RUNTIME_DIRECTORY = Path("/run/poppy-agent-rehearsal")
SERVICE_USER = "poppy-agent-rehearsal"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main() -> int:
    _guard_environment()
    server_url = os.environ["POPPY_E2E_SERVER_URL"].rstrip("/")
    bootstrap_token = os.environ["POPPY_E2E_AGENT_TOKEN"]
    python_executable = _required_executable("POPPY_SYSTEMD_REHEARSAL_PYTHON")
    server_container = os.environ.get("POPPY_SYSTEMD_SERVER_CONTAINER", "poppy-app")
    robot_id: UUID | None = None

    try:
        _run_static_verify()
        _ensure_service_user()
        _ensure_source_readable()
        robot_id = _create_robot(server_url, bootstrap_token)
        _prepare_env(server_url, bootstrap_token, robot_id)
        wrapper_path = _write_fixture_entrypoint()
        _write_test_unit(python_executable, wrapper_path)
        _systemctl("daemon-reload")
        _systemctl("enable", UNIT_NAME)

        _phase("systemd clean start", lambda: _clean_start(server_url, robot_id))
        _phase("Server-unavailable startup retry", lambda: _delayed_server_start(server_url))
        _phase(
            "runtime Server outage and reconnect",
            lambda: _server_outage(server_url, server_container),
        )
        _phase(
            "process crash and active Execution recovery",
            lambda: _active_crash(server_url, robot_id),
        )
        _phase(
            "graceful restart and status lifecycle",
            lambda: _graceful_restart(server_url, robot_id),
        )
        _phase("journald secret safety", _check_journal_safety)
        print("SYSTEMD RECOVERY REHEARSAL PASSED")
        return 0
    except (OSError, RehearsalError, ValueError) as exc:
        print(f"SYSTEMD RECOVERY REHEARSAL FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        _cleanup_unit()
        if robot_id is not None:
            _retire_robot(server_url, bootstrap_token, robot_id)


def _guard_environment() -> None:
    if platform.system() != "Linux":
        raise RehearsalError("Linux systemd environment is required")
    if os.geteuid() != 0:
        raise RehearsalError("run this guarded rehearsal as root in a disposable Linux environment")
    if os.environ.get("POPPY_SYSTEMD_REHEARSAL") != "1":
        raise RehearsalError("POPPY_SYSTEMD_REHEARSAL=1 is required")
    server_url = os.environ.get("POPPY_E2E_SERVER_URL", "")
    parsed = urlparse(server_url)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise RehearsalError("only an HTTP localhost Server target is allowed")
    if not os.environ.get("POPPY_E2E_AGENT_TOKEN", "").strip():
        raise RehearsalError("POPPY_E2E_AGENT_TOKEN is required")
    if os.environ.get("ROBOT_MODE", "mock").strip().lower() == "unitree":
        raise RehearsalError("Unitree mode is forbidden")
    if shutil.which("systemctl") is None or shutil.which("systemd-analyze") is None:
        raise RehearsalError("systemd tools are unavailable")
    running = _command("systemctl", "is-system-running", allow_failure=True).strip()
    if running not in {"running", "degraded"}:
        raise RehearsalError("systemd PID 1 is not running")


def _required_executable(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    path = Path(value)
    if not path.is_absolute() or not os.access(path, os.X_OK):
        raise RehearsalError(f"{name} must point to an executable Linux Python")
    return path


def _run_static_verify() -> None:
    source = PRODUCTION_UNIT.read_text(encoding="utf-8")
    required = (
        "Wants=network-online.target",
        "After=network-online.target",
        "Type=simple",
        "RuntimeDirectory=poppy-agent",
        "Restart=on-failure",
        "TimeoutStopSec=15",
    )
    if any(value not in source for value in required):
        raise RehearsalError("production systemd unit is missing a required lifecycle directive")
    result = subprocess.run(
        ["systemd-analyze", "verify", str(PRODUCTION_UNIT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("systemd unit static verify: PASS")
        return

    normalized = Path("/run/poppy-agent-static-verify.service")
    normalized_source = source
    for old, new in (
        ("User=poppy", "User=root"),
        ("WorkingDirectory=/home/poppy/projects/Poppy-agent", "WorkingDirectory=/"),
        ("EnvironmentFile=/etc/poppy-agent/poppy-agent.env", "EnvironmentFile=/dev/null"),
        (
            "ExecStart=/home/poppy/projects/Poppy-agent/.venv/bin/python -m poppy_agent.main",
            "ExecStart=/usr/bin/true",
        ),
    ):
        normalized_source = normalized_source.replace(old, new)
    normalized.write_text(normalized_source, encoding="utf-8")
    _command("chmod", "0644", str(normalized))
    try:
        normalized_result = subprocess.run(
            ["systemd-analyze", "verify", str(normalized)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        normalized.unlink(missing_ok=True)
    if normalized_result.returncode != 0:
        raise RehearsalError("production systemd unit failed normalized systemd-analyze verify")
    print("systemd unit contract/static verify: PASS (deployment paths normalized)")


def _ensure_service_user() -> None:
    if (
        subprocess.run(
            ["getent", "passwd", SERVICE_USER], capture_output=True, check=False
        ).returncode
        != 0
    ):
        _command(
            "useradd",
            "--system",
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            SERVICE_USER,
        )


def _ensure_source_readable() -> None:
    if not (ROOT / "src" / "poppy_agent" / "main.py").is_file():
        raise RehearsalError("Agent source is not readable from the Linux environment")


def _create_robot(server_url: str, token: str) -> UUID:
    data = _request(
        server_url,
        "POST",
        "/api/v1/admin/robots",
        token,
        {
            "alias": f"systemd-rehearsal-{uuid4().hex}",
            "model": "mock",
            "edition": "development",
            "firmwareVersion": "mock",
            "sdkVersion": "not-applicable",
            "agentId": None,
            "capabilities": [],
            "safetyProfileId": None,
            "isExternal": False,
        },
    )
    value = data.get("robotId")
    if not isinstance(value, str):
        raise RehearsalError("Server returned a malformed Robot identity")
    return UUID(value)


def _prepare_env(server_url: str, token: str, robot_id: UUID, *, delayed: bool = False) -> None:
    target = "http://127.0.0.1:18991" if delayed else server_url
    values = {
        "ROBOT_MODE": "mock",
        "POPPY_ROBOT_ID": str(robot_id),
        "POPPY_SERVER_URL": target,
        "POPPY_AGENT_TOKEN": token,
        "POPPY_AGENT_NAME": f"systemd-rehearsal-agent-{robot_id}",
        "POPPY_AGENT_VERSION": "0.1.0",
        "POPPY_SDK_VERSION": "not-applicable",
        "POPPY_AGENT_PLATFORM": "ubuntu-systemd-rehearsal",
        "POPPY_HEARTBEAT_INTERVAL_SECONDS": "0.2",
        "POPPY_EXECUTION_POLL_INTERVAL_SECONDS": "0.1",
        "POPPY_SERVER_CONNECT_TIMEOUT_SECONDS": "0.5",
        "POPPY_SERVER_READ_TIMEOUT_SECONDS": "1",
        "POPPY_SERVER_MAX_RETRIES": "0",
        "POPPY_SERVER_RECONNECT_INITIAL_DELAY_SECONDS": "0.1",
        "POPPY_SERVER_RECONNECT_MAX_DELAY_SECONDS": "0.5",
        "POPPY_RUNTIME_STATUS_PATH": str(RUNTIME_DIRECTORY / "status.json"),
    }
    ENV_PATH.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )
    _command("chown", f"{SERVICE_USER}:{SERVICE_USER}", str(ENV_PATH))
    _command("chmod", "0640", str(ENV_PATH))


def _write_fixture_entrypoint() -> Path:
    path = Path("/run/poppy-agent-systemd-fixture.py")
    path.write_text(
        """from uuid import UUID
from poppy_agent.execution import InterruptibleSleeper, MockExecutionExecutor
import poppy_agent.main as main


def create_mock_executor(config):
    if config.robot_mode != "mock":
        raise RuntimeError("systemd rehearsal requires mock mode")
    return MockExecutionExecutor(
        bound_robot_id=UUID(config.robot_id),
        sleeper=InterruptibleSleeper(),
    )


main._create_mock_executor = create_mock_executor
raise SystemExit(main.main())
""",
        encoding="utf-8",
    )
    _command("chown", f"{SERVICE_USER}:{SERVICE_USER}", str(path))
    _command("chmod", "0644", str(path))
    return path


def _write_test_unit(python_executable: Path, wrapper_path: Path) -> None:
    source = PRODUCTION_UNIT.read_text(encoding="utf-8")
    replacements = {
        "Description=Poppy-Agent runtime": (
            "Description=Poppy-Agent software-only systemd rehearsal"
        ),
        "User=poppy": f"User={SERVICE_USER}",
        "WorkingDirectory=/home/poppy/projects/Poppy-agent": f"WorkingDirectory={ROOT}",
        "EnvironmentFile=/etc/poppy-agent/poppy-agent.env": f"EnvironmentFile={ENV_PATH}",
        "RuntimeDirectory=poppy-agent": "RuntimeDirectory=poppy-agent-rehearsal",
        "ExecStart=/home/poppy/projects/Poppy-agent/.venv/bin/python -m poppy_agent.main": (
            f"ExecStart={python_executable} {wrapper_path}"
        ),
    }
    for old, new in replacements.items():
        if old not in source:
            raise RehearsalError(f"production unit contract changed: {old}")
        source = source.replace(old, new)
    source = source.replace(
        f"EnvironmentFile={ENV_PATH}\n",
        f"EnvironmentFile={ENV_PATH}\nEnvironment=PYTHONPATH={ROOT / 'src'}\n",
    )
    UNIT_PATH.write_text(source, encoding="utf-8")
    _command("chmod", "0644", str(UNIT_PATH))


def _clean_start(server_url: str, robot_id: UUID) -> bool:
    _prepare_env(server_url, os.environ["POPPY_E2E_AGENT_TOKEN"], robot_id)
    _systemctl("start", UNIT_NAME)
    _wait_ready()
    _patch_robot_ready(server_url, robot_id)
    _wait_status(lambda value: value.get("operationalReady") is True)
    return True


def _delayed_server_start(server_url: str) -> bool:
    _systemctl("stop", UNIT_NAME)
    _prepare_env(server_url, os.environ["POPPY_E2E_AGENT_TOKEN"], _robot_from_env(), delayed=True)
    _systemctl("reset-failed", UNIT_NAME, allow_failure=True)
    _systemctl("start", UNIT_NAME)
    _wait_for_restart()
    _prepare_env(server_url, os.environ["POPPY_E2E_AGENT_TOKEN"], _robot_from_env())
    _wait_ready(timeout=25)
    return True


def _server_outage(server_url: str, container: str) -> bool:
    _docker("inspect", container)
    _docker("stop", container)
    try:
        _wait_status(lambda value: value.get("connectivityState") == "DEGRADED")
        if _systemctl("is-active", UNIT_NAME, allow_failure=True).strip() != "active":
            raise RehearsalError("Agent service stopped during Server outage")
    finally:
        _docker("start", container)
    _wait_status(
        lambda value: (
            value.get("operationalReady") is True and value.get("connectivityState") == "CONNECTED"
        ),
        timeout=30,
    )
    return True


def _active_crash(server_url: str, robot_id: UUID) -> bool:
    session_token, execution_id = _create_long_execution(server_url)
    _wait_execution(server_url, session_token, execution_id, "RUNNING")
    _systemctl("kill", "--kill-who=main", "--signal=SIGKILL", UNIT_NAME)
    _wait_for_restart()
    _wait_execution(server_url, session_token, execution_id, "FAILED", timeout=30)
    _wait_robot_release(server_url, robot_id)
    _wait_ready(timeout=30)
    return True


def _graceful_restart(server_url: str, robot_id: UUID) -> bool:
    _systemctl("restart", UNIT_NAME)
    _wait_ready()
    status = _read_status()
    if status.get("activeExecutionId") is not None:
        raise RehearsalError("graceful restart retained an active execution")
    _wait_robot_release(server_url, robot_id)
    _systemctl("stop", UNIT_NAME)
    _wait_inactive()
    if RUNTIME_DIRECTORY.exists():
        raise RehearsalError("RuntimeDirectory remained after service stop")
    _systemctl("start", UNIT_NAME)
    _wait_ready()
    return True


def _check_journal_safety() -> bool:
    output = _command("journalctl", "-u", UNIT_NAME, "--no-pager", "-n", "200", "-o", "cat")
    forbidden = (
        os.environ["POPPY_E2E_AGENT_TOKEN"],
        "X-Agent-Token",
        "Authorization",
        "commandPayload",
        "sessionToken",
        "recoveryCode",
    )
    if any(value and value in output for value in forbidden):
        raise RehearsalError("journal contained a secret or raw command field")
    return True


def _create_long_execution(server_url: str) -> tuple[str, UUID]:
    session = _request(server_url, "POST", "/api/v1/sessions", None, {})
    session_id = _string(session, "sessionId")
    session_token = _string(session, "sessionToken")
    document = {
        "schemaVersion": 1,
        "blocks": [
            {"id": "start-1", "type": "START", "parameters": {}},
            {"id": "wait-1", "type": "WAIT", "parameters": {"durationSeconds": 30}},
            {"id": "end-1", "type": "END", "parameters": {}},
        ],
    }
    revision = _request(
        server_url,
        "POST",
        f"/api/v1/sessions/{session_id}/block-revisions",
        session_token,
        {"document": document},
        session_token=True,
    )
    block_version = revision.get("blockVersion")
    if not isinstance(block_version, int):
        raise RehearsalError("Server returned a malformed block revision")
    _request(
        server_url,
        "POST",
        f"/api/v1/sessions/{session_id}/simulation-passes",
        session_token,
        {"blockVersion": block_version},
        session_token=True,
    )
    execution = _request(
        server_url,
        "POST",
        f"/api/v1/sessions/{session_id}/executions",
        session_token,
        {"blockVersion": block_version},
        session_token=True,
    )
    return session_token, UUID(_string(execution, "executionId"))


def _patch_robot_ready(server_url: str, robot_id: UUID) -> None:
    capabilities = [
        {"code": "telemetry", "status": "UNVERIFIED"},
        *(
            {"code": code, "status": "VERIFIED"}
            for code in ("COMMAND_MOVE", "COMMAND_TURN", "COMMAND_POSTURE", "COMMAND_STOP")
        ),
    ]
    _request(
        server_url,
        "PATCH",
        f"/api/v1/admin/robots/{robot_id}",
        os.environ["POPPY_E2E_AGENT_TOKEN"],
        {"capabilities": capabilities},
    )


def _retire_robot(server_url: str, token: str, robot_id: UUID) -> None:
    try:
        _request(
            server_url,
            "PATCH",
            f"/api/v1/admin/robots/{robot_id}",
            token,
            {"operationalStatus": "UNAVAILABLE"},
        )
    except Exception:
        return


def _robot_from_env() -> UUID:
    value = _read_env_value("POPPY_ROBOT_ID")
    return UUID(value)


def _read_env_value(name: str) -> str:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key == name:
            return value
    raise RehearsalError(f"rehearsal environment is missing {name}")


def _read_status() -> dict[str, Any]:
    path = RUNTIME_DIRECTORY / "status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("status snapshot is unavailable or malformed") from exc
    if not isinstance(value, dict):
        raise RehearsalError("status snapshot is not a JSON object")
    return value


def _wait_status(predicate: Any, *, timeout: float = 20) -> None:
    _wait_until(lambda: predicate(_read_status()), timeout)


def _wait_ready(*, timeout: float = 20) -> None:
    _wait_status(
        lambda value: (
            value.get("operationalReady") is True
            and value.get("connectivityState") == "CONNECTED"
            and value.get("activeExecutionId") is None
        ),
        timeout=timeout,
    )


def _wait_for_restart(*, timeout: float = 20) -> None:
    _wait_until(lambda: _restart_count() >= 1, timeout)


def _restart_count() -> int:
    output = _command("systemctl", "show", UNIT_NAME, "-p", "NRestarts", "--value")
    try:
        return int(output.strip())
    except ValueError as exc:
        raise RehearsalError("systemd returned an invalid restart count") from exc


def _wait_inactive(*, timeout: float = 15) -> None:
    _wait_until(
        lambda: _systemctl("is-active", UNIT_NAME, allow_failure=True).strip() != "active", timeout
    )


def _wait_execution(
    server_url: str, session_token: str, execution_id: UUID, expected: str, *, timeout: float = 20
) -> None:
    _wait_until(
        lambda: (
            _execution_status(server_url, session_token, execution_id).get("status") == expected
        ),
        timeout,
    )


def _execution_status(server_url: str, session_token: str, execution_id: UUID) -> dict[str, Any]:
    return _request(
        server_url,
        "GET",
        f"/api/v1/executions/{execution_id}",
        session_token,
        None,
        session_token=True,
    )


def _wait_robot_release(server_url: str, robot_id: UUID, *, timeout: float = 20) -> None:
    def released() -> bool:
        data = _request(
            server_url,
            "GET",
            "/api/v1/admin/robots",
            os.environ["POPPY_E2E_AGENT_TOKEN"],
            None,
        )
        robots = data.get("robots")
        if not isinstance(robots, list):
            raise RehearsalError("Server returned malformed Robot list")
        return any(
            isinstance(value, dict)
            and value.get("robotId") == str(robot_id)
            and value.get("occupied") is False
            and value.get("currentExecutionId") is None
            for value in robots
        )

    _wait_until(released, timeout)


def _wait_until(predicate: Any, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, RehearsalError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise RehearsalError("bounded wait timed out")


def _request(
    server_url: str,
    method: str,
    path: str,
    token: str | None,
    payload: dict[str, object] | None,
    *,
    session_token: bool = False,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["X-Session-Token" if session_token else "X-Agent-Token"] = token
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{server_url}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RehearsalError(f"HTTP {exc.code} for {method} {path}") from exc
    except urllib.error.URLError as exc:
        raise RehearsalError(f"transport failure for {method} {path}") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("Server returned malformed JSON") from exc
    if not isinstance(body, dict) or body.get("success") is not True:
        raise RehearsalError("Server returned an invalid API envelope")
    data_value = body.get("data")
    if not isinstance(data_value, dict):
        raise RehearsalError("Server returned malformed data")
    return data_value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RehearsalError(f"Server response is missing {key}")
    return value


def _command(*args: str, allow_failure: bool = False) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0 and not allow_failure:
        raise RehearsalError(f"command failed: {args[0]}")
    return result.stdout


def _systemctl(*args: str, allow_failure: bool = False) -> str:
    return _command("systemctl", *args, allow_failure=allow_failure)


def _docker(*args: str) -> str:
    if shutil.which("docker") is None:
        raise RehearsalError("docker is required for the Server outage phase")
    return _command("docker", *args)


def _phase(name: str, action: Any) -> None:
    action()
    print(f"{name}: PASS")


def _cleanup_unit() -> None:
    _systemctl("disable", "--now", UNIT_NAME, allow_failure=True)
    _systemctl("daemon-reload", allow_failure=True)
    for path in (UNIT_PATH, ENV_PATH, Path("/run/poppy-agent-systemd-fixture.py")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    if (
        subprocess.run(
            ["getent", "passwd", SERVICE_USER], capture_output=True, check=False
        ).returncode
        == 0
    ):
        _command("userdel", SERVICE_USER, allow_failure=True)


if __name__ == "__main__":
    raise SystemExit(main())
