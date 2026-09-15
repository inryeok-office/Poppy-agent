"""Small HTTP client for the Poppy-Server Agent endpoints."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from poppy_agent.server.config import ServerConfig
from poppy_agent.server.models import (
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    ServerExecutionDelivery,
    ServerExecutionReportStatus,
    ServerExecutionStatusResponse,
)


class ServerClientError(RuntimeError):
    """Base error for safe, non-secret server client failures."""


class ServerApiError(ServerClientError):
    """Raised for a non-success HTTP response."""

    def __init__(self, status_code: int, error_code: str | None) -> None:
        self.status_code = status_code
        self.error_code = error_code
        code = f" ({error_code})" if error_code else ""
        super().__init__(f"Poppy-Server returned HTTP {status_code}{code}")


class ServerTransportError(ServerClientError):
    """Raised for bounded timeout or connection failures."""


class ServerResponseError(ServerClientError):
    """Raised when a success response does not match the server envelope."""


class ServerClient:
    """Call the Poppy-Server Agent registration, heartbeat, and execution APIs."""

    def __init__(
        self,
        config: ServerConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=config.server_url,
            headers={"X-Agent-Token": config.agent_token},
            timeout=httpx.Timeout(
                connect=config.connect_timeout_seconds,
                read=config.read_timeout_seconds,
                write=config.read_timeout_seconds,
                pool=config.connect_timeout_seconds,
            ),
            transport=transport,
        )

    def register_agent(self, request: AgentRegistrationRequest) -> AgentRegistrationResponse:
        """Register an Agent and return the server-assigned Agent ID."""
        data = self._request_data(
            "POST",
            "/api/v1/internal/agents/register",
            expected_status=201,
            payload=request.to_json(),
        )
        response = AgentRegistrationResponse(
            agent_id=_uuid_field(data, "agentId"),
            registered_at=_datetime_field(data, "registeredAt"),
            accepted_robot_ids=_uuid_list_field(data, "acceptedRobotIds"),
            agent_token=_string_field(data, "agentToken"),
        )
        self._client.headers["X-Agent-Token"] = response.agent_token
        return response

    def send_heartbeat(self, agent_id: UUID, request: HeartbeatRequest) -> HeartbeatResponse:
        """Send one heartbeat and return the server acceptance timestamp."""
        data = self._request_data(
            "POST",
            f"/api/v1/internal/agents/{agent_id}/heartbeat",
            expected_status=200,
            payload=request.to_json(),
        )
        return HeartbeatResponse(
            agent_id=_uuid_field(data, "agentId"),
            accepted_at=_datetime_field(data, "acceptedAt"),
        )

    def fetch_next_execution(
        self, agent_id: UUID, robot_id: UUID
    ) -> ServerExecutionDelivery | None:
        """Fetch an assigned execution, or return None when no work is available."""
        data = self._request_data(
            "GET",
            f"/api/v1/internal/agents/{agent_id}/executions/next",
            expected_status=200,
            params={"robotId": str(robot_id)},
        )
        if "execution" not in data:
            raise ServerResponseError("Poppy-Server execution response is malformed")
        execution = data["execution"]
        if execution is None:
            return None
        if not isinstance(execution, dict):
            raise ServerResponseError("Poppy-Server execution response is malformed")

        status = execution.get("status")
        if status != "ASSIGNED":
            raise ServerResponseError("Poppy-Server execution status is unsupported")
        protocol_version = _int_field(execution, "protocolVersion")
        if protocol_version != 1:
            raise ServerResponseError("Poppy-Server execution protocol version is unsupported")
        delivery_robot_id = _uuid_field(execution, "robotId")
        if delivery_robot_id != robot_id:
            raise ServerResponseError(
                "Poppy-Server execution robot identity does not match request"
            )
        return ServerExecutionDelivery(
            execution_id=_uuid_field(execution, "executionId"),
            robot_id=delivery_robot_id,
            status=status,
            protocol_version=protocol_version,
        )

    def report_execution_status(
        self,
        agent_id: UUID,
        execution_id: UUID,
        robot_id: UUID,
        status: ServerExecutionReportStatus | str,
    ) -> ServerExecutionStatusResponse:
        """Report one execution status and validate the server identity response."""
        report_status = _execution_report_status(status)
        data = self._request_data(
            "POST",
            f"/api/v1/internal/agents/{agent_id}/executions/{execution_id}/status",
            expected_status=200,
            payload={"robotId": str(robot_id), "status": report_status.value},
        )
        response_execution_id = _uuid_field(data, "executionId")
        response_robot_id = _uuid_field(data, "robotId")
        response_status = _execution_report_status(data.get("status"))
        if response_execution_id != execution_id:
            raise ServerResponseError(
                "Poppy-Server execution response identity does not match request"
            )
        if response_robot_id != robot_id:
            raise ServerResponseError(
                "Poppy-Server execution response robot does not match request"
            )
        if response_status != report_status:
            raise ServerResponseError(
                "Poppy-Server execution response status does not match request"
            )
        return ServerExecutionStatusResponse(
            execution_id=response_execution_id,
            robot_id=response_robot_id,
            status=response_status,
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> ServerClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_data(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        payload: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, payload=payload, params=params)
        if response.status_code != expected_status:
            raise ServerApiError(response.status_code, _error_code(response))

        try:
            body = response.json()
        except ValueError as exc:
            raise ServerResponseError("Poppy-Server returned malformed JSON") from exc

        if not isinstance(body, dict) or body.get("success") is not True:
            raise ServerResponseError("Poppy-Server returned an invalid response envelope")
        data = body.get("data")
        if not isinstance(data, dict):
            raise ServerResponseError("Poppy-Server response data is malformed")
        return data

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None,
        params: dict[str, str] | None,
    ) -> httpx.Response:
        for attempt in range(self._config.max_retries + 1):
            try:
                return self._client.request(method, path, json=payload, params=params)
            except httpx.TimeoutException as exc:
                if attempt < self._config.max_retries:
                    self._sleep(0.1 * (2**attempt))
                    continue
                raise ServerTransportError("Poppy-Server request timed out") from exc
            except httpx.TransportError as exc:
                if attempt < self._config.max_retries:
                    self._sleep(0.1 * (2**attempt))
                    continue
                raise ServerTransportError("Poppy-Server connection failed") from exc
        raise AssertionError("unreachable retry state")


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def _uuid_field(data: dict[str, Any], name: str) -> UUID:
    value = data.get(name)
    if not isinstance(value, str):
        raise ServerResponseError("Poppy-Server response UUID is malformed")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ServerResponseError("Poppy-Server response UUID is malformed") from exc


def _uuid_list_field(data: dict[str, Any], name: str) -> tuple[UUID, ...]:
    value = data.get(name)
    if not isinstance(value, list):
        raise ServerResponseError("Poppy-Server response UUID list is malformed")
    if not all(isinstance(item, str) for item in value):
        raise ServerResponseError("Poppy-Server response UUID list is malformed")
    try:
        return tuple(UUID(item) for item in value)
    except ValueError as exc:
        raise ServerResponseError("Poppy-Server response UUID list is malformed") from exc


def _string_field(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ServerResponseError("Poppy-Server response string is malformed")
    return value


def _datetime_field(data: dict[str, Any], name: str) -> datetime:
    value = data.get(name)
    if not isinstance(value, str):
        raise ServerResponseError("Poppy-Server response timestamp is malformed")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ServerResponseError("Poppy-Server response timestamp is malformed") from exc


def _int_field(data: dict[str, Any], name: str) -> int:
    value = data.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ServerResponseError("Poppy-Server response integer is malformed")
    return value


def _execution_report_status(value: object) -> ServerExecutionReportStatus:
    if not isinstance(value, str):
        raise ServerResponseError("Poppy-Server execution report status is unsupported")
    try:
        return ServerExecutionReportStatus(value)
    except ValueError as exc:
        raise ServerResponseError("Poppy-Server execution report status is unsupported") from exc
