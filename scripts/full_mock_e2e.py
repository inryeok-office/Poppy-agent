"""Run the full Poppy-Server to Poppy-Agent Mock execution flow over HTTP."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from rehearsal_safety import is_allowed_loopback_server_url  # noqa: E402

from poppy_agent.agent import create_agent  # noqa: E402
from poppy_agent.command import (  # noqa: E402
    CommandType,
    HighLevelCommandProtocolParser,
    MoveDirection,
    MoveParameters,
    Posture,
    PostureParameters,
    StopParameters,
    TurnDirection,
    TurnParameters,
    WaitParameters,
)
from poppy_agent.config import AgentConfig  # noqa: E402
from poppy_agent.execution import ExecutionStatus, MockExecutionExecutor  # noqa: E402
from poppy_agent.server import (  # noqa: E402
    AgentServerRuntime,
    ServerClient,
    ServerConfig,
    ServerExecutionReportStatus,
    ServerExecutionStatusResponse,
)

COMMAND_CAPABILITIES = {
    "COMMAND_MOVE",
    "COMMAND_TURN",
    "COMMAND_POSTURE",
    "COMMAND_STOP",
}


class FullMockE2EError(RuntimeError):
    """Raised when the live Full Mock E2E contract is not satisfied."""


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so the localhost safety boundary cannot be bypassed."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request:
        raise FullMockE2EError("HTTP redirects are not allowed by the local E2E harness")


@dataclass(frozen=True, slots=True)
class E2EConfig:
    server_url: str
    agent_token: str
    timeout_seconds: float
    poll_interval_seconds: float
    http_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> E2EConfig:
        server_url = os.environ.get("POPPY_E2E_SERVER_URL", "").strip().rstrip("/")
        agent_token = os.environ.get("POPPY_E2E_AGENT_TOKEN", "")
        if not is_allowed_loopback_server_url(server_url):
            raise FullMockE2EError(
                "POPPY_E2E_SERVER_URL must be an http localhost URL; production targets are blocked"
            )
        if not agent_token.strip():
            raise FullMockE2EError("POPPY_E2E_AGENT_TOKEN is required")
        return cls(
            server_url=server_url,
            agent_token=agent_token,
            timeout_seconds=_positive_float("POPPY_E2E_TIMEOUT_SECONDS", 30.0, maximum=120.0),
            poll_interval_seconds=_positive_float(
                "POPPY_E2E_POLL_INTERVAL_SECONDS", 0.2, maximum=5.0
            ),
            http_timeout_seconds=_positive_float(
                "POPPY_E2E_HTTP_TIMEOUT_SECONDS", 5.0, maximum=30.0
            ),
        )


class E2EHttpClient:
    """Small JSON client for public and admin Server APIs used by the harness."""

    def __init__(self, base_url: str, timeout_seconds: float, secret: str) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._secret = secret
        self._opener = urllib.request.build_opener(_RejectRedirectHandler())

    def post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        expected_status: int = 200,
        session_token: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            path,
            payload=payload,
            expected_status=expected_status,
            session_token=session_token,
        )

    def get(
        self,
        path: str,
        *,
        expected_status: int = 200,
        session_token: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            path,
            expected_status=expected_status,
            session_token=session_token,
        )

    def patch(
        self,
        path: str,
        payload: dict[str, object],
        *,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        return self.request("PATCH", path, payload=payload, expected_status=expected_status)

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        expected_status: int,
        session_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if session_token is not None:
            headers["X-Session-Token"] = session_token
        encoded = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=encoded,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            raise FullMockE2EError(
                f"{method} {path} returned HTTP {exc.code}: {self._safe_text(raw)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise FullMockE2EError(f"{method} {path} failed: {exc.reason}") from exc
        if status != expected_status:
            raise FullMockE2EError(
                f"{method} {path} returned HTTP {status}: {self._safe_text(raw)}"
            )
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FullMockE2EError(f"{method} {path} returned malformed JSON") from exc
        if not isinstance(body, dict) or body.get("success") is not True:
            raise FullMockE2EError(f"{method} {path} returned an invalid API envelope")
        data = body.get("data")
        if not isinstance(data, dict):
            raise FullMockE2EError(f"{method} {path} returned malformed data")
        return data

    def _safe_text(self, raw: bytes) -> str:
        value = raw.decode("utf-8", errors="replace")
        return value.replace(self._secret, "<redacted>")[:1000]


class RecordingServerClient(ServerClient):
    """Keep the real HTTP client while recording status report order."""

    def __init__(self, config: ServerConfig) -> None:
        super().__init__(config)
        self.reported_statuses: list[ServerExecutionReportStatus] = []

    def report_execution_status(
        self,
        agent_id: UUID,
        execution_id: UUID,
        robot_id: UUID,
        status: ServerExecutionReportStatus | str,
    ) -> ServerExecutionStatusResponse:
        response = super().report_execution_status(agent_id, execution_id, robot_id, status)
        self.reported_statuses.append(response.status)
        return response


def main() -> int:
    config = E2EConfig.from_environment()
    http = E2EHttpClient(config.server_url, config.http_timeout_seconds, config.agent_token)
    run_id = uuid4().hex
    agent_name = f"poppy-full-mock-e2e-{run_id}"
    runtime: AgentServerRuntime | None = None

    try:
        robot = http.post(
            "/api/v1/admin/robots",
            {
                "alias": f"full-mock-e2e-{run_id}",
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
        robot_id = UUID(_required_string(robot, "robotId"))
        print(f"Robot fixture created: {robot_id}")

        session = http.post("/api/v1/sessions", {}, expected_status=201)
        session_id = UUID(_required_string(session, "sessionId"))
        session_token = _required_string(session, "sessionToken")
        print(f"Session created: {session_id}")

        block_program = _block_program()
        revision = http.post(
            f"/api/v1/sessions/{session_id}/block-revisions",
            {"document": block_program},
            expected_status=201,
            session_token=session_token,
        )
        block_version = _required_int(revision, "blockVersion")
        _assert(block_version == 1, f"expected first block version 1, got {block_version}")
        print(f"Block Revision created: version={block_version}")

        simulation = http.post(
            f"/api/v1/sessions/{session_id}/simulation-passes",
            {"blockVersion": block_version},
            expected_status=201,
            session_token=session_token,
        )
        _assert(
            _required_int(simulation, "blockVersion") == block_version,
            "Simulation Pass block version mismatch",
        )
        print("Simulation Pass recorded")

        execution = http.post(
            f"/api/v1/sessions/{session_id}/executions",
            {"blockVersion": block_version},
            expected_status=201,
            session_token=session_token,
        )
        execution_id = UUID(_required_string(execution, "executionId"))
        _assert(_required_string(execution, "status") == "QUEUED", "initial status is not QUEUED")
        print(f"Execution requested: {execution_id} status=QUEUED")

        newer_revision = http.post(
            f"/api/v1/sessions/{session_id}/block-revisions",
            {"document": _newer_block_program()},
            expected_status=201,
            session_token=session_token,
        )
        _assert(
            _required_int(newer_revision, "blockVersion") == 2,
            "newer Block Revision was not version 2",
        )
        print("Newer Block Revision appended; execution snapshot must remain version 1")

        mock_config = AgentConfig(robot_mode="mock", robot_id=str(robot_id))
        _assert(mock_config.robot_mode == "mock", "Full Mock E2E safety guard failed")
        server_config = ServerConfig(
            server_url=config.server_url,
            agent_token=config.agent_token,
            agent_name=agent_name,
            agent_version="0.1.0",
            sdk_version="not-applicable",
            platform="full-mock-e2e",
            heartbeat_interval_seconds=30.0,
            execution_poll_interval_seconds=config.poll_interval_seconds,
            connect_timeout_seconds=config.http_timeout_seconds,
            read_timeout_seconds=config.http_timeout_seconds,
            max_retries=0,
        )
        server_client = RecordingServerClient(server_config)
        runtime = AgentServerRuntime(create_agent(mock_config), server_client, server_config)
        registration = runtime.start()
        _assert(robot_id in registration.accepted_robot_ids, "Agent did not accept Mock Robot")
        print(f"Agent registered: {registration.agent_id}")

        capabilities = [{"code": "telemetry", "status": "UNVERIFIED"}]
        capabilities.extend(
            {"code": code, "status": "VERIFIED"} for code in sorted(COMMAND_CAPABILITIES)
        )
        http.patch(f"/api/v1/admin/robots/{robot_id}", {"capabilities": capabilities})
        robot_after_capabilities = _find_robot(http, robot_id)
        _assert_verified_capabilities(robot_after_capabilities)
        print("Robot command capabilities prepared as explicitly VERIFIED")

        runtime.heartbeat_once()
        ready_robot = _wait_for(
            "Mock Robot ONLINE and READY",
            lambda: _find_robot(http, robot_id),
            lambda value: (
                value.get("connectionStatus") == "ONLINE"
                and value.get("operationalStatus") == "READY"
            ),
            config,
        )
        _assert(ready_robot.get("occupied") is False, "Robot became occupied before allocation")
        print("Agent heartbeat accepted: Robot ONLINE + READY")

        assigned_status = _wait_for(
            "Execution ASSIGNED",
            lambda: _execution_status(http, session_token, execution_id),
            lambda value: (
                value.get("status") == "ASSIGNED" and value.get("assignedRobotId") == str(robot_id)
            ),
            config,
        )
        _assert(assigned_status.get("blockVersion") == block_version, "assigned version mismatch")
        print("Queue scheduler allocation confirmed: ASSIGNED")

        delivery = server_client.fetch_next_execution(registration.agent_id, robot_id)
        _assert(delivery is not None, "assigned execution was not delivered")
        _assert(delivery.execution_id == execution_id, "delivery execution ID mismatch")
        parsed_program = HighLevelCommandProtocolParser().parse(delivery.command_payload)
        _assert(
            json.loads(delivery.command_payload) == _compiled_snapshot(),
            "delivered command snapshot differs from the compiled version 1 program",
        )
        print(
            "commandPayload strict parse confirmed: "
            f"{len(parsed_program.commands)} typed commands in immutable snapshot"
        )

        executor = MockExecutionExecutor(bound_robot_id=robot_id)
        result = runtime.execution_once(executor)
        _assert(result is not None, "Agent execution_once returned no work after ASSIGNED")
        _assert(result.execution_id == execution_id, "ExecutionResult ID mismatch")
        _assert(result.status is ExecutionStatus.COMPLETED, "Mock execution did not complete")
        _assert(
            server_client.reported_statuses
            == [
                ServerExecutionReportStatus.RUNNING,
                ServerExecutionReportStatus.COMPLETED,
            ],
            "Agent status report order mismatch",
        )
        print("Agent HTTP status reports confirmed: RUNNING -> COMPLETED")
        expected_types = [
            CommandType.WAIT,
            CommandType.MOVE,
            CommandType.TURN,
            CommandType.POSTURE,
            CommandType.POSTURE,
            CommandType.STOP,
        ]
        expected_sources = [
            "wait-1",
            "move-forward-1",
            "turn-left-1",
            "sit-1",
            "stand-1",
            "stop-1",
        ]
        _assert(
            [event.type for event in executor.events] == expected_types,
            "trace type order mismatch",
        )
        _assert(
            [event.source_block_id for event in executor.events] == expected_sources,
            "trace sourceBlockId order mismatch",
        )
        _assert(executor.events[0].parameters == WaitParameters(1.5), "WAIT parameter mismatch")
        _assert(
            executor.events[1].parameters == MoveParameters(MoveDirection.FORWARD, 1.25),
            "MOVE parameter mismatch",
        )
        _assert(
            executor.events[2].parameters == TurnParameters(TurnDirection.LEFT, 90.0),
            "TURN parameter mismatch",
        )
        _assert(executor.events[3].parameters == PostureParameters(Posture.SIT), "SIT mismatch")
        _assert(executor.events[4].parameters == PostureParameters(Posture.STAND), "STAND mismatch")
        _assert(
            isinstance(executor.events[5].parameters, StopParameters),
            "STOP parameter mismatch",
        )
        print("Mock trace: " + ", ".join(event.type.value for event in executor.events))
        print("Mock STOP termination confirmed: command after STOP was not dispatched")

        completed_status = _wait_for(
            "Execution COMPLETED",
            lambda: _execution_status(http, session_token, execution_id),
            lambda value: value.get("status") == "COMPLETED",
            config,
        )
        _assert(
            completed_status.get("assignedRobotId") == str(robot_id),
            "completed robot mismatch",
        )
        print("Server terminal status confirmed: COMPLETED")

        _wait_for(
            "Robot release",
            lambda: _find_robot(http, robot_id),
            lambda value: (
                value.get("occupied") is False and value.get("currentExecutionId") is None
            ),
            config,
        )
        _assert(runtime.active_execution_id is None, "Agent retained active execution")
        print("Robot release confirmed: occupied=false, currentExecutionId=null")

        _assert(runtime.execution_once(executor) is None, "completed execution was delivered again")
        print("Post-completion Agent polling confirmed: no work")
        print("FULL MOCK E2E PASSED")
        return 0
    finally:
        if runtime is not None:
            runtime.shutdown()


def _block_program() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "blocks": [
            {"id": "start-1", "type": "START", "parameters": {}},
            {"id": "wait-1", "type": "WAIT", "parameters": {"durationSeconds": 1.5}},
            {
                "id": "move-forward-1",
                "type": "MOVE_FORWARD",
                "parameters": {"distanceMeters": 1.25},
            },
            {
                "id": "turn-left-1",
                "type": "TURN_LEFT",
                "parameters": {"angleDegrees": 90.0},
            },
            {"id": "sit-1", "type": "SIT", "parameters": {}},
            {"id": "stand-1", "type": "STAND", "parameters": {}},
            {"id": "stop-1", "type": "STOP", "parameters": {}},
            {"id": "after-stop-1", "type": "WAIT", "parameters": {"durationSeconds": 999.0}},
            {"id": "end-1", "type": "END", "parameters": {}},
        ],
    }


def _newer_block_program() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "blocks": [
            {"id": "start-newer", "type": "START", "parameters": {}},
            {"id": "wait-newer", "type": "WAIT", "parameters": {"durationSeconds": 999.0}},
            {"id": "end-newer", "type": "END", "parameters": {}},
        ],
    }


def _compiled_snapshot() -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "commands": [
            {
                "sequence": 0,
                "sourceBlockId": "wait-1",
                "type": "WAIT",
                "parameters": {"durationSeconds": 1.5},
            },
            {
                "sequence": 1,
                "sourceBlockId": "move-forward-1",
                "type": "MOVE",
                "parameters": {"direction": "FORWARD", "distanceMeters": 1.25},
            },
            {
                "sequence": 2,
                "sourceBlockId": "turn-left-1",
                "type": "TURN",
                "parameters": {"direction": "LEFT", "angleDegrees": 90.0},
            },
            {
                "sequence": 3,
                "sourceBlockId": "sit-1",
                "type": "POSTURE",
                "parameters": {"posture": "SIT"},
            },
            {
                "sequence": 4,
                "sourceBlockId": "stand-1",
                "type": "POSTURE",
                "parameters": {"posture": "STAND"},
            },
            {
                "sequence": 5,
                "sourceBlockId": "stop-1",
                "type": "STOP",
                "parameters": {},
            },
            {
                "sequence": 6,
                "sourceBlockId": "after-stop-1",
                "type": "WAIT",
                "parameters": {"durationSeconds": 999.0},
            },
        ],
    }


def _execution_status(
    http: E2EHttpClient, session_token: str, execution_id: UUID
) -> dict[str, Any]:
    return http.get(f"/api/v1/executions/{execution_id}", session_token=session_token)


def _find_robot(http: E2EHttpClient, robot_id: UUID) -> dict[str, Any]:
    data = http.get("/api/v1/admin/robots")
    robots = data.get("robots")
    if not isinstance(robots, list):
        raise FullMockE2EError("Robot list response is malformed")
    for robot in robots:
        if isinstance(robot, dict) and robot.get("robotId") == str(robot_id):
            return robot
    raise FullMockE2EError(f"Robot {robot_id} was not found in admin list")


def _assert_verified_capabilities(robot: dict[str, Any]) -> None:
    capabilities = robot.get("capabilities")
    if not isinstance(capabilities, list):
        raise FullMockE2EError("Robot capabilities response is malformed")
    verified = {
        item.get("code")
        for item in capabilities
        if isinstance(item, dict) and item.get("status") == "VERIFIED"
    }
    _assert(
        COMMAND_CAPABILITIES.issubset(verified),
        "required command capabilities are not VERIFIED",
    )


def _wait_for(
    description: str,
    probe: Callable[[], dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    config: E2EConfig,
) -> dict[str, Any]:
    deadline = monotonic() + config.timeout_seconds
    latest: dict[str, Any] = {}
    while monotonic() < deadline:
        latest = probe()
        if predicate(latest):
            return latest
        time.sleep(min(config.poll_interval_seconds, max(0.0, deadline - monotonic())))
    raise FullMockE2EError(f"timeout waiting for {description}; last={_safe_value(latest)}")


def _positive_float(name: str, default: float, *, maximum: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = default if not raw else float(raw)
    except ValueError as exc:
        raise FullMockE2EError(f"{name} must be a number") from exc
    if value <= 0 or value > maximum:
        raise FullMockE2EError(f"{name} must be > 0 and <= {maximum}")
    return value


def _required_string(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise FullMockE2EError(f"response field {name} is malformed")
    return value


def _required_int(data: dict[str, Any], name: str) -> int:
    value = data.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise FullMockE2EError(f"response field {name} is malformed")
    return value


def _safe_value(value: object) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))[:1000]


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise FullMockE2EError(message)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FullMockE2EError as exc:
        print(f"FULL MOCK E2E FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
