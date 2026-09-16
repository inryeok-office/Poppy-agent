import pytest

from poppy_agent.config import AgentConfig, ConfigurationError


def test_config_loads_explicit_mock_configuration() -> None:
    config = AgentConfig.from_environment({"ROBOT_MODE": " MOCK ", "POPPY_ROBOT_ID": "test-robot"})

    assert config == AgentConfig(robot_mode="mock", robot_id="test-robot")


def test_physical_execution_flag_defaults_to_disabled_and_parses_explicit_boolean() -> None:
    default_config = AgentConfig.from_environment(
        {"ROBOT_MODE": "mock", "POPPY_ROBOT_ID": "test-robot"}
    )
    enabled_config = AgentConfig.from_environment(
        {
            "ROBOT_MODE": "mock",
            "POPPY_ROBOT_ID": "test-robot",
            "POPPY_ENABLE_PHYSICAL_EXECUTION": " TRUE ",
        }
    )

    assert default_config.enable_physical_execution is False
    assert enabled_config.enable_physical_execution is True


def test_invalid_physical_execution_flag_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="POPPY_ENABLE_PHYSICAL_EXECUTION"):
        AgentConfig.from_environment(
            {
                "ROBOT_MODE": "mock",
                "POPPY_ROBOT_ID": "test-robot",
                "POPPY_ENABLE_PHYSICAL_EXECUTION": "yes",
            }
        )


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"POPPY_ROBOT_ID": "test-robot"}, "ROBOT_MODE is required"),
        ({"ROBOT_MODE": "mock"}, "POPPY_ROBOT_ID is required"),
        ({"ROBOT_MODE": "unsupported", "POPPY_ROBOT_ID": "test-robot"}, "mock or unitree"),
    ],
)
def test_invalid_config_is_rejected(environment: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        AgentConfig.from_environment(environment)


def test_unitree_config_requires_explicit_network_and_identity_metadata() -> None:
    config = AgentConfig.from_environment(
        {
            "ROBOT_MODE": "unitree",
            "POPPY_ROBOT_ID": "robot-id",
            "UNITREE_NETWORK_INTERFACE": "enp2s0",
            "POPPY_ROBOT_MODEL": "GO2",
            "POPPY_ROBOT_EDITION": "EDU",
            "POPPY_ROBOT_FIRMWARE_VERSION": "provided-by-operator",
            "UNITREE_SDK_VERSION": "unitree_sdk2_python",
        }
    )

    assert config.network_interface == "enp2s0"
    assert config.robot_model == "GO2"
