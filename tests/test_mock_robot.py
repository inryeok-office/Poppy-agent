import pytest

from poppy_agent.robot import MockRobotAdapter, MockRobotSpec
from poppy_agent.robot.mock import RobotNotInitializedError


def test_mock_robot_initialization_identity_status_and_capabilities() -> None:
    adapter = MockRobotAdapter(
        MockRobotSpec(
            robot_id="test-robot",
            model="mock-model",
            edition="test",
            firmware_version="1.0.0",
            sdk_version="mock-sdk",
            battery_percent=87,
            current_execution_id=None,
        )
    )

    with pytest.raises(RobotNotInitializedError):
        adapter.status()

    adapter.initialize()

    assert adapter.identity().robot_id == "test-robot"
    assert adapter.identity().model == "mock-model"
    assert adapter.status().battery_percent == 87
    assert adapter.status().current_execution_id is None
    assert adapter.capabilities() == (
        "telemetry",
        "COMMAND_MOVE",
        "COMMAND_TURN",
        "COMMAND_POSTURE",
        "COMMAND_STOP",
    )


def test_mock_robot_shutdown_is_safe() -> None:
    adapter = MockRobotAdapter(MockRobotSpec(robot_id="test-robot"))
    adapter.initialize()
    adapter.shutdown()
    adapter.shutdown()

    with pytest.raises(RobotNotInitializedError):
        adapter.identity()
