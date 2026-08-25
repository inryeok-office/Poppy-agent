"""Robot adapter contracts and implementations."""

from poppy_agent.robot.adapter import (
    RobotAdapter,
    RobotIdentity,
    RobotStatus,
)
from poppy_agent.robot.mock import MockRobotAdapter, MockRobotSpec

__all__ = [
    "MockRobotAdapter",
    "MockRobotSpec",
    "RobotAdapter",
    "RobotIdentity",
    "RobotStatus",
]
