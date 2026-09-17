import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from poppy_agent.server import (
    AgentRegistrationRequest,
    HeartbeatRequest,
    HeartbeatRobotRequest,
    RobotRegistrationRequest,
    ServerApiError,
    ServerClient,
    ServerConfig,
    ServerExecutionLifecycleStatus,
    ServerExecutionRecoveryAction,
    ServerExecutionRecoveryResponse,
    ServerExecutionReportStatus,
    ServerExecutionStateResponse,
    ServerExecutionStatusResponse,
    ServerResponseError,
    ServerTransportError,
)
from poppy_agent.server.models import ServerExecutionDelivery

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000003")


def client_for(handler, *, max_retries: int = 0, sleep=None) -> ServerClient:
    return ServerClient(
        ServerConfig(
            server_url="https://server.example.test",
            agent_token="dummy-agent-token",
            agent_name="agent-test",
            agent_version="0.1.0",
            sdk_version="not-applicable",
            platform="test",
            max_retries=max_retries,
        ),
        transport=httpx.MockTransport(handler),
        sleep=sleep or (lambda _: None),
    )


def registration_request() -> AgentRegistrationRequest:
    return AgentRegistrationRequest(
        agent_name="agent-test",
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="test",
        robots=(
            RobotRegistrationRequest(
                robot_id=ROBOT_ID,
                model="GO2",
                edition="EDU",
                firmware_version="1.0.0",
                capabilities=("TELEMETRY",),
            ),
        ),
    )


def test_register_maps_request_header_and_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/internal/agents/register"
        assert request.headers["X-Agent-Token"] == "dummy-agent-token"
        body = json.loads(request.content)
        assert body["robots"][0]["robotId"] == str(ROBOT_ID)
        return httpx.Response(
            201,
            json={
                "success": True,
                "data": {
                    "agentId": str(AGENT_ID),
                    "registeredAt": "2026-08-25T10:20:30",
                    "acceptedRobotIds": [str(ROBOT_ID)],
                    "agentToken": "issued-agent-token",
                },
                "error": None,
            },
        )

    client = client_for(handler)
    response = client.register_agent(registration_request())
    client.close()

    assert response.agent_id == AGENT_ID
    assert response.agent_token == "issued-agent-token"
    assert "issued-agent-token" not in repr(response)
    assert response.accepted_robot_ids == (ROBOT_ID,)
    assert response.registered_at == datetime(2026, 8, 25, 10, 20, 30)


def test_register_preserves_bootstrap_token_for_legacy_server_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Agent-Token"] == "dummy-agent-token"
        if request.url.path.endswith("/register"):
            return httpx.Response(
                201,
                json={
                    "success": True,
                    "data": {
                        "agentId": str(AGENT_ID),
                        "registeredAt": "2026-08-25T10:20:30",
                        "acceptedRobotIds": [str(ROBOT_ID)],
                    },
                    "error": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "agentId": str(AGENT_ID),
                    "acceptedAt": "2026-08-25T10:20:31",
                },
                "error": None,
            },
        )

    client = client_for(handler)
    response = client.register_agent(registration_request())
    client.send_heartbeat(
        AGENT_ID,
        HeartbeatRequest(
            sent_at=datetime(2026, 8, 25, 10, 20, 30, tzinfo=UTC),
            robots=(),
        ),
    )
    client.close()

    assert response.agent_token is None


def test_heartbeat_preserves_nullable_and_omitted_execution_fields() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"agentId": str(AGENT_ID), "acceptedAt": "2026-08-25T10:20:31"},
                "error": None,
            },
        )

    client = client_for(handler)
    client.send_heartbeat(
        AGENT_ID,
        HeartbeatRequest(
            sent_at=datetime(2026, 8, 25, 10, 20, 30, tzinfo=UTC),
            robots=(
                HeartbeatRobotRequest(
                    robot_id=ROBOT_ID,
                    connection_status="ONLINE",
                    operational_status="READY",
                    battery_percent=None,
                    current_execution_id=None,
                ),
            ),
        ),
    )
    client.send_heartbeat(
        AGENT_ID,
        HeartbeatRequest(
            sent_at=datetime(2026, 8, 25, 10, 20, 30),
            robots=(
                HeartbeatRobotRequest(
                    robot_id=ROBOT_ID,
                    connection_status="OFFLINE",
                    operational_status="UNAVAILABLE",
                    battery_percent=75,
                    current_execution_id=AGENT_ID,
                    current_execution_id_provided=False,
                ),
            ),
        ),
    )
    client.close()

    assert payloads[0]["sentAt"] == "2026-08-25T10:20:30"
    assert payloads[0]["robots"][0]["currentExecutionId"] is None
    assert "currentExecutionId" not in payloads[1]["robots"][0]


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(400, "COMMON_400"), (401, "AGENT_AUTH_INVALID"), (409, "AGENT_ALREADY_REGISTERED")],
)
def test_http_error_is_typed_without_echoing_token(status_code: int, error_code: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "success": False,
                "data": None,
                "error": {"code": error_code, "message": "safe test message"},
            },
        )

    client = client_for(handler)
    with pytest.raises(ServerApiError) as raised:
        client.register_agent(registration_request())
    client.close()

    assert raised.value.status_code == status_code
    assert raised.value.error_code == error_code
    assert "dummy-agent-token" not in str(raised.value)


def test_timeout_retries_once_then_raises_safe_error() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("test timeout", request=request)

    client = client_for(handler, max_retries=1, sleep=delays.append)
    with pytest.raises(ServerTransportError, match="timed out"):
        client.register_agent(registration_request())
    client.close()

    assert calls == 2
    assert delays == [0.1]


def test_connection_failure_and_malformed_response_are_reported() -> None:
    def connection_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test connection failure", request=request)

    client = client_for(connection_failure)
    with pytest.raises(ServerTransportError, match="connection failed"):
        client.register_agent(registration_request())
    client.close()

    client = client_for(lambda _: httpx.Response(201, text="not-json"))
    with pytest.raises(ServerResponseError, match="malformed JSON"):
        client.register_agent(registration_request())
    client.close()


def test_fetch_next_execution_maps_assigned_delivery_and_request() -> None:
    execution_id = UUID("00000000-0000-0000-0000-000000000003")
    command_payload = '{"protocolVersion":1,"commands":[]}'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/internal/agents/{AGENT_ID}/executions/next"
        assert request.url.params["robotId"] == str(ROBOT_ID)
        assert request.headers["X-Agent-Token"] == "dummy-agent-token"
        assert request.content == b""
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "execution": {
                        "executionId": str(execution_id),
                        "robotId": str(ROBOT_ID),
                        "status": "ASSIGNED",
                        "protocolVersion": 1,
                        "commandPayload": command_payload,
                    }
                },
                "error": None,
            },
        )

    client = client_for(handler)
    delivery = client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()

    assert delivery == ServerExecutionDelivery(
        execution_id=execution_id,
        robot_id=ROBOT_ID,
        status="ASSIGNED",
        protocol_version=1,
        command_payload=command_payload,
    )


@pytest.mark.parametrize("command_payload", [None, {}, [], 1, " "])
def test_fetch_next_execution_rejects_missing_or_malformed_command_payload(
    command_payload: object,
) -> None:
    client = client_for(
        lambda _: httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "execution": {
                        "executionId": str(EXECUTION_ID),
                        "robotId": str(ROBOT_ID),
                        "status": "ASSIGNED",
                        "protocolVersion": 1,
                        "commandPayload": command_payload,
                    }
                },
                "error": None,
            },
        )
    )

    with pytest.raises(ServerResponseError, match="command payload"):
        client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()


def test_fetch_next_execution_returns_none_when_no_work_is_available() -> None:
    client = client_for(
        lambda _: httpx.Response(
            200, json={"success": True, "data": {"execution": None}, "error": None}
        )
    )

    assert client.fetch_next_execution(AGENT_ID, ROBOT_ID) is None
    client.close()


@pytest.mark.parametrize(
    ("execution", "message"),
    [
        (
            {
                "executionId": "not-a-uuid",
                "robotId": str(ROBOT_ID),
                "status": "ASSIGNED",
                "protocolVersion": 1,
                "commandPayload": '{"protocolVersion":1,"commands":[]}',
            },
            "UUID",
        ),
        (
            {
                "executionId": str(AGENT_ID),
                "robotId": str(ROBOT_ID),
                "status": "QUEUED",
                "protocolVersion": 1,
            },
            "status",
        ),
        (
            {
                "executionId": str(AGENT_ID),
                "robotId": str(ROBOT_ID),
                "status": "ASSIGNED",
                "protocolVersion": 2,
            },
            "protocol version",
        ),
    ],
)
def test_fetch_next_execution_rejects_invalid_delivery(
    execution: dict[str, object], message: str
) -> None:
    client = client_for(
        lambda _: httpx.Response(
            200, json={"success": True, "data": {"execution": execution}, "error": None}
        )
    )

    with pytest.raises(ServerResponseError, match=message):
        client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()


def test_fetch_next_execution_rejects_delivery_for_a_different_robot() -> None:
    other_robot_id = UUID("00000000-0000-0000-0000-000000000004")
    client = client_for(
        lambda _: httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "execution": {
                        "executionId": str(AGENT_ID),
                        "robotId": str(other_robot_id),
                        "status": "ASSIGNED",
                        "protocolVersion": 1,
                    }
                },
                "error": None,
            },
        )
    )

    with pytest.raises(ServerResponseError, match="robot identity"):
        client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()


@pytest.mark.parametrize(
    "body",
    [
        {"success": True, "data": {}, "error": None},
        {"success": True, "data": {"execution": []}, "error": None},
        {"success": False, "data": {"execution": None}, "error": None},
    ],
)
def test_fetch_next_execution_rejects_malformed_envelope(body: dict[str, object]) -> None:
    client = client_for(lambda _: httpx.Response(200, json=body))

    with pytest.raises(ServerResponseError):
        client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()


@pytest.mark.parametrize("status_code", [401, 404, 409, 500])
def test_fetch_next_execution_preserves_http_error_contract(status_code: int) -> None:
    client = client_for(
        lambda _: httpx.Response(
            status_code,
            json={"success": False, "data": None, "error": {"code": "SERVER_ERROR"}},
        )
    )

    with pytest.raises(ServerApiError) as raised:
        client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()

    assert raised.value.status_code == status_code
    assert "dummy-agent-token" not in str(raised.value)


def test_fetch_next_execution_retries_timeout_then_reports_safe_error() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("test timeout", request=request)

    client = client_for(handler, max_retries=1, sleep=delays.append)
    with pytest.raises(ServerTransportError, match="timed out") as raised:
        client.fetch_next_execution(AGENT_ID, ROBOT_ID)
    client.close()

    assert calls == 2
    assert delays == [0.1]
    assert "dummy-agent-token" not in str(raised.value)


def status_response(
    status: ServerExecutionReportStatus | str,
    *,
    execution_id: UUID = EXECUTION_ID,
    robot_id: UUID = ROBOT_ID,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "data": {
                "executionId": str(execution_id),
                "robotId": str(robot_id),
                "status": str(status),
            },
            "error": None,
        },
    )


@pytest.mark.parametrize("status", list(ServerExecutionReportStatus))
def test_report_execution_status_maps_request_and_response(
    status: ServerExecutionReportStatus,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert (
            request.url.path
            == f"/api/v1/internal/agents/{AGENT_ID}/executions/{EXECUTION_ID}/status"
        )
        assert request.headers["X-Agent-Token"] == "dummy-agent-token"
        assert json.loads(request.content) == {
            "robotId": str(ROBOT_ID),
            "status": status.value,
        }
        return status_response(status)

    client = client_for(handler)
    response = client.report_execution_status(AGENT_ID, EXECUTION_ID, ROBOT_ID, status)
    client.close()

    assert response == ServerExecutionStatusResponse(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        status=status,
    )


def test_get_execution_status_maps_cancellation_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (
            request.url.path
            == f"/api/v1/internal/agents/{AGENT_ID}/executions/{EXECUTION_ID}/status"
        )
        assert request.url.params["robotId"] == str(ROBOT_ID)
        assert request.headers["X-Agent-Token"] == "dummy-agent-token"
        return status_response(ServerExecutionReportStatus.CANCELLED)

    client = client_for(handler)
    response = client.get_execution_status(AGENT_ID, EXECUTION_ID, ROBOT_ID)
    client.close()

    assert response == ServerExecutionStateResponse(
        execution_id=EXECUTION_ID,
        robot_id=ROBOT_ID,
        status=ServerExecutionLifecycleStatus.CANCELLED,
    )


def test_get_execution_status_accepts_assigned_lifecycle_state() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return status_response("ASSIGNED")

    client = client_for(handler)
    response = client.get_execution_status(AGENT_ID, EXECUTION_ID, ROBOT_ID)
    client.close()

    assert response.status is ServerExecutionLifecycleStatus.ASSIGNED


def test_discover_active_execution_maps_bound_running_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == (
            f"/api/v1/internal/agents/{AGENT_ID}/robots/{ROBOT_ID}/active-execution"
        )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "activeExecution": {
                        "executionId": str(EXECUTION_ID),
                        "robotId": str(ROBOT_ID),
                        "status": "RUNNING",
                    }
                },
                "error": None,
            },
        )

    client = client_for(handler)
    response = client.discover_active_execution(AGENT_ID, ROBOT_ID)
    client.close()

    assert response is not None
    assert response.execution_id == EXECUTION_ID
    assert response.status is ServerExecutionLifecycleStatus.RUNNING


def test_discover_active_execution_accepts_no_active_execution() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": True, "data": {"activeExecution": None}, "error": None},
        )

    client = client_for(handler)
    response = client.discover_active_execution(AGENT_ID, ROBOT_ID)
    client.close()

    assert response is None


def test_recover_active_execution_maps_reconciliation_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            f"/api/v1/internal/agents/{AGENT_ID}/robots/{ROBOT_ID}/active-execution/recover"
        )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "robotId": str(ROBOT_ID),
                    "executionId": str(EXECUTION_ID),
                    "previousStatus": "RUNNING",
                    "status": "FAILED",
                    "action": "RECOVERED_AS_FAILED",
                },
                "error": None,
            },
        )

    client = client_for(handler)
    response = client.recover_active_execution(AGENT_ID, ROBOT_ID)
    client.close()

    assert response == ServerExecutionRecoveryResponse(
        robot_id=ROBOT_ID,
        execution_id=EXECUTION_ID,
        previous_status=ServerExecutionLifecycleStatus.RUNNING,
        status=ServerExecutionLifecycleStatus.FAILED,
        action=ServerExecutionRecoveryAction.RECOVERED_AS_FAILED,
    )


def test_report_execution_status_rejects_unsupported_request_status_without_transport() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return status_response("QUEUED")

    client = client_for(handler)
    with pytest.raises(ServerResponseError, match="unsupported"):
        client.report_execution_status(AGENT_ID, EXECUTION_ID, ROBOT_ID, "QUEUED")
    client.close()

    assert calls == 0


@pytest.mark.parametrize("status_code", [401, 404, 409, 500])
def test_report_execution_status_preserves_http_error_and_hides_token(status_code: int) -> None:
    client = client_for(
        lambda _: httpx.Response(
            status_code,
            json={
                "success": False,
                "data": None,
                "error": {
                    "code": "STATUS_ERROR",
                    "message": "dummy-agent-token must not be exposed",
                },
            },
        )
    )

    with pytest.raises(ServerApiError) as raised:
        client.report_execution_status(
            AGENT_ID, EXECUTION_ID, ROBOT_ID, ServerExecutionReportStatus.RUNNING
        )
    client.close()

    assert raised.value.status_code == status_code
    assert "dummy-agent-token" not in str(raised.value)


@pytest.mark.parametrize(
    "body",
    [
        "not-json",
        {"success": True, "data": None, "error": None},
        {"success": True, "data": {}, "error": None},
        {
            "success": True,
            "data": {
                "executionId": "not-a-uuid",
                "robotId": str(ROBOT_ID),
                "status": "RUNNING",
            },
            "error": None,
        },
    ],
)
def test_report_execution_status_rejects_malformed_response(body: object) -> None:
    response = httpx.Response(200, text=body if isinstance(body, str) else None, json=None)
    if not isinstance(body, str):
        response = httpx.Response(200, json=body)
    client = client_for(lambda _: response)

    with pytest.raises(ServerResponseError):
        client.report_execution_status(
            AGENT_ID, EXECUTION_ID, ROBOT_ID, ServerExecutionReportStatus.RUNNING
        )
    client.close()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("executionId", str(AGENT_ID), "identity"),
        ("robotId", str(AGENT_ID), "robot"),
        ("status", "FAILED", "status"),
    ],
)
def test_report_execution_status_rejects_mismatched_response(
    field: str, value: str, message: str
) -> None:
    response_body = {
        "success": True,
        "data": {
            "executionId": str(EXECUTION_ID),
            "robotId": str(ROBOT_ID),
            "status": "RUNNING",
        },
        "error": None,
    }
    response_body["data"][field] = value
    client = client_for(lambda _: httpx.Response(200, json=response_body))

    with pytest.raises(ServerResponseError, match=message):
        client.report_execution_status(
            AGENT_ID, EXECUTION_ID, ROBOT_ID, ServerExecutionReportStatus.RUNNING
        )
    client.close()


def test_report_execution_status_retries_timeout_then_reports_safe_error() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("test timeout", request=request)

    client = client_for(handler, max_retries=1, sleep=delays.append)
    with pytest.raises(ServerTransportError, match="timed out"):
        client.report_execution_status(
            AGENT_ID, EXECUTION_ID, ROBOT_ID, ServerExecutionReportStatus.RUNNING
        )
    client.close()

    assert calls == 2
    assert delays == [0.1]


def test_report_execution_status_connection_failure_is_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test connection failure", request=request)

    client = client_for(handler)
    with pytest.raises(ServerTransportError, match="connection failed"):
        client.report_execution_status(
            AGENT_ID, EXECUTION_ID, ROBOT_ID, ServerExecutionReportStatus.RUNNING
        )
    client.close()
