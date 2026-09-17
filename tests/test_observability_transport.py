import logging
from uuid import UUID

import httpx
import pytest

from poppy_agent.observability import SERVER_REQUEST_FAILED, SERVER_REQUEST_RETRY
from poppy_agent.server import (
    AgentRegistrationRequest,
    RobotRegistrationRequest,
    ServerClient,
    ServerConfig,
    ServerTransportError,
)

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _request() -> AgentRegistrationRequest:
    return AgentRegistrationRequest(
        agent_name="agent-test",
        agent_version="0.1.0",
        sdk_version="not-applicable",
        platform="test",
        robots=(
            RobotRegistrationRequest(
                robot_id=ROBOT_ID,
                model="mock",
                edition="development",
                firmware_version="mock",
                capabilities=("TELEMETRY",),
            ),
        ),
    )


def test_transport_retry_and_exhaustion_are_structured_and_secret_safe(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret=should-not-be-logged", request=request)

    client = ServerClient(
        ServerConfig(
            server_url="https://server.example.test",
            agent_token="runtime-secret-token",
            agent_name="agent-test",
            agent_version="0.1.0",
            sdk_version="not-applicable",
            platform="test",
            max_retries=1,
        ),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with caplog.at_level(logging.WARNING, logger="poppy_agent.server.client"):
        with pytest.raises(ServerTransportError):
            client.register_agent(_request())
    client.close()

    events = [record.poppy_event for record in caplog.records]
    assert events == [SERVER_REQUEST_RETRY, SERVER_REQUEST_FAILED]
    assert "runtime-secret-token" not in caplog.text
    assert "secret=should-not-be-logged" not in caplog.text
    assert "X-Agent-Token" not in caplog.text
