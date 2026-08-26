import pytest

from poppy_agent.server import ServerConfig, ServerConfigurationError


def test_server_config_loads_metadata_and_transport_settings() -> None:
    config = ServerConfig.from_environment(
        {
            "POPPY_SERVER_URL": "https://server.example.test/",
            "POPPY_AGENT_TOKEN": "dummy-agent-token",
            "POPPY_AGENT_NAME": "agent-test",
            "POPPY_AGENT_VERSION": "0.1.0",
            "POPPY_SDK_VERSION": "not-applicable",
            "POPPY_AGENT_PLATFORM": "test",
            "POPPY_HEARTBEAT_INTERVAL_SECONDS": "12.5",
            "POPPY_SERVER_CONNECT_TIMEOUT_SECONDS": "2",
            "POPPY_SERVER_READ_TIMEOUT_SECONDS": "4",
            "POPPY_SERVER_MAX_RETRIES": "0",
        }
    )

    assert config.server_url == "https://server.example.test"
    assert config.heartbeat_interval_seconds == 12.5
    assert config.max_retries == 0
    assert "dummy-agent-token" not in repr(config)


def test_server_config_requires_token_and_valid_url() -> None:
    with pytest.raises(ServerConfigurationError, match="POPPY_SERVER_URL"):
        ServerConfig(
            server_url="not-a-url",
            agent_token="dummy-agent-token",
            agent_name="agent",
            agent_version="0.1.0",
            sdk_version="mock",
            platform="test",
        )

    with pytest.raises(ServerConfigurationError, match="POPPY_AGENT_TOKEN"):
        ServerConfig(
            server_url="https://server.example.test",
            agent_token="",
            agent_name="agent",
            agent_version="0.1.0",
            sdk_version="mock",
            platform="test",
        )
