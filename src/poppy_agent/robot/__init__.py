"""Robot adapter contracts and implementations."""

from poppy_agent.robot.adapter import (
    RobotAdapter,
    RobotIdentity,
    RobotStatus,
)
from poppy_agent.robot.mock import MockRobotAdapter, MockRobotSpec
from poppy_agent.robot.unitree import (
    UnitreeGo2Adapter,
    UnitreeGo2Config,
    UnitreeSdkUnavailableError,
)

__all__ = [
    "MockRobotAdapter",
    "MockRobotSpec",
    "RobotAdapter",
    "RobotIdentity",
    "RobotStatus",
    "UnitreeGo2Adapter",
    "UnitreeGo2Config",
    "UnitreeSdkUnavailableError",
]
