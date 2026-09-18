"""Hardware command boundary implementations and test doubles."""

from poppy_agent.hardware.boundary import (
    FakeHardwareBackend,
    FakeHardwareBackendError,
    FakeHardwareEvent,
    HardwareCommandIntent,
    HardwareCommandPort,
    HardwareCommandTarget,
)
from poppy_agent.hardware.factory import create_unitree_execution_executor
from poppy_agent.hardware.unitree import (
    FakeUnitreeCall,
    FakeUnitreeCommandClient,
    UnitreeCommandBackend,
    UnitreeCommandBackendError,
    UnitreeCommandClient,
    UnitreeCommandOperation,
)
from poppy_agent.hardware.unitree_sdk import (
    UnitreeMotionCommand,
    UnitreeMotionMapper,
    UnitreeSdkCommandClient,
    UnitreeSdkCommandError,
    UnitreeSdkUnavailableError,
    default_unitree_sport_client_factory,
)

__all__ = [
    "FakeHardwareBackend",
    "FakeHardwareBackendError",
    "FakeHardwareEvent",
    "HardwareCommandIntent",
    "HardwareCommandPort",
    "HardwareCommandTarget",
    "FakeUnitreeCall",
    "FakeUnitreeCommandClient",
    "UnitreeCommandBackend",
    "UnitreeCommandBackendError",
    "UnitreeCommandClient",
    "UnitreeCommandOperation",
    "UnitreeMotionCommand",
    "UnitreeMotionMapper",
    "UnitreeSdkCommandClient",
    "UnitreeSdkCommandError",
    "UnitreeSdkUnavailableError",
    "default_unitree_sport_client_factory",
    "create_unitree_execution_executor",
]
