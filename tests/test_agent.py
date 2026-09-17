import pytest

from poppy_agent.agent import Agent, AgentState, create_agent
from poppy_agent.config import AgentConfig
from poppy_agent.robot import MockRobotAdapter, MockRobotSpec


def test_agent_startup_captures_robot_snapshot_and_shutdown() -> None:
    config = AgentConfig(robot_mode="mock", robot_id="test-robot")
    agent = create_agent(config)

    assert agent.state is AgentState.CREATED
    snapshot = agent.start()

    assert agent.state is AgentState.RUNNING
    assert snapshot.identity.robot_id == "test-robot"
    assert snapshot.status.connection_status == "ONLINE"
    assert snapshot.capabilities == (
        "telemetry",
        "COMMAND_MOVE",
        "COMMAND_TURN",
        "COMMAND_POSTURE",
        "COMMAND_STOP",
    )

    agent.shutdown()
    agent.shutdown()
    assert agent.state is AgentState.STOPPED


def test_agent_rejects_invalid_lifecycle_transitions() -> None:
    config = AgentConfig(robot_mode="mock", robot_id="test-robot")
    agent = Agent(config, MockRobotAdapter(MockRobotSpec(robot_id="test-robot")))

    agent.start()
    with pytest.raises(RuntimeError, match="cannot start"):
        agent.start()

    agent.shutdown()
    with pytest.raises(RuntimeError, match="cannot start"):
        agent.start()
