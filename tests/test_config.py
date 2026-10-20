import pytest

from poppy_agent.config import AgentConfig, ConfigurationError


def test_config_loads_explicit_mock_configuration() -> None:
    config = AgentConfig.from_environment({"ROBOT_MODE": " MOCK ", "POPPY_ROBOT_ID": "test-robot"})

    assert config == AgentConfig(robot_mode="mock", robot_id="test-robot")


def test_physical_execution_flag_defaults_to_disabled_and_parses_explicit_boolean() -> None:
    default_config = AgentConfig.from_environment(
        {"ROBOT_MODE": "mock", "POPPY_ROBOT_ID": "test-robot"}
    )

    assert default_config.enable_physical_execution is False


def _physical_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "ROBOT_MODE": "mock",
        "POPPY_ROBOT_ID": "test-robot",
        "POPPY_ENABLE_PHYSICAL_EXECUTION": "true",
        "POPPY_PHYSICAL_MOTION_PROFILE_NAME": "reviewed-test-profile",
        "POPPY_PHYSICAL_MOTION_PROFILE_VERSION": "test-v1",
        "POPPY_PHYSICAL_ALLOWED_COMMANDS": "MOVE,TURN",
        "POPPY_PHYSICAL_MAX_MOVE_DISTANCE_METERS": "0.25",
        "POPPY_PHYSICAL_MAX_TURN_ANGLE_DEGREES": "15",
        "POPPY_PHYSICAL_MAX_LINEAR_RATE_METERS_PER_SECOND": "0.1",
        "POPPY_PHYSICAL_MAX_ANGULAR_RATE_DEGREES_PER_SECOND": "15",
        "POPPY_PHYSICAL_MAX_COMMAND_DURATION_SECONDS": "3",
        "POPPY_PHYSICAL_MIN_BATTERY_PERCENT": "50",
    }
    environment.update(overrides)
    return environment


def test_physical_execution_requires_complete_explicit_policy() -> None:
    config = AgentConfig.from_environment(_physical_environment())

    assert config.enable_physical_execution is True
    assert config.physical_motion_profile_name == "reviewed-test-profile"
    assert config.physical_motion_policy is not None
    assert config.physical_minimum_battery_percent == 50


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("POPPY_PHYSICAL_MOTION_PROFILE_NAME", ""),
        ("POPPY_PHYSICAL_ALLOWED_COMMANDS", "MOVE,PRESET"),
        ("POPPY_PHYSICAL_MAX_MOVE_DISTANCE_METERS", "NaN"),
        ("POPPY_PHYSICAL_MAX_COMMAND_DURATION_SECONDS", "0"),
        ("POPPY_PHYSICAL_MIN_BATTERY_PERCENT", "101"),
        ("POPPY_PHYSICAL_MIN_BATTERY_PERCENT", "50.0"),
    ],
)
def test_physical_execution_rejects_missing_or_invalid_policy(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError, match=name):
        AgentConfig.from_environment(_physical_environment(**{name: value}))


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
            "POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS": "15",
        }
    )

    assert config.network_interface == "enp2s0"
    assert config.robot_model == "GO2"
    assert config.unitree_telemetry_stale_timeout_seconds == 15.0


@pytest.mark.parametrize("value", ["", "0", "-1", "NaN", "Infinity", "invalid"])
def test_unitree_config_requires_positive_finite_telemetry_stale_timeout(value: str) -> None:
    environment = {
        "ROBOT_MODE": "unitree",
        "POPPY_ROBOT_ID": "robot-id",
        "UNITREE_NETWORK_INTERFACE": "enp2s0",
        "POPPY_ROBOT_MODEL": "GO2",
        "POPPY_ROBOT_EDITION": "EDU",
        "POPPY_ROBOT_FIRMWARE_VERSION": "provided-by-operator",
        "UNITREE_SDK_VERSION": "unitree_sdk2_python",
        "POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS": value,
    }

    with pytest.raises(ConfigurationError, match="POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS"):
        AgentConfig.from_environment(environment)
