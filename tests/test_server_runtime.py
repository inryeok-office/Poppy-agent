import json
from uuid import UUID

import httpx
import pytest

from poppy_agent.agent import create_agent
from poppy_agent.config import AgentConfig
from poppy_agent.server import (
    AgentServerRuntime,
    AgentServerRuntimeError,
    ServerClient,
    ServerConfig,
)

ROBOT_ID = "00000000-0000-0000-0000-000000000001"
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")


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
