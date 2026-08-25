import pytest

from poppy_agent.config import AgentConfig, ConfigurationError


def test_config_loads_explicit_mock_configuration() -> None:
    config = AgentConfig.from_environment({"ROBOT_MODE": " MOCK ", "POPPY_ROBOT_ID": "test-robot"})

    assert config == AgentConfig(robot_mode="mock", robot_id="test-robot")


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"POPPY_ROBOT_ID": "test-robot"}, "ROBOT_MODE is required"),
        ({"ROBOT_MODE": "mock"}, "POPPY_ROBOT_ID is required"),
        ({"ROBOT_MODE": "unitree", "POPPY_ROBOT_ID": "test-robot"}, "only ROBOT_MODE=mock"),
    ],
)
def test_invalid_config_is_rejected(environment: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        AgentConfig.from_environment(environment)
