"""Hardware command boundary implementations and test doubles."""

from poppy_agent.hardware.boundary import (
    FakeHardwareBackend,
    FakeHardwareBackendError,
    FakeHardwareEvent,
    HardwareCommandIntent,
    HardwareCommandPort,
    HardwareCommandTarget,
)
from poppy_agent.hardware.unitree import (
    FakeUnitreeCall,
    FakeUnitreeCommandClient,
    UnitreeCommandBackend,
    UnitreeCommandBackendError,
    UnitreeCommandClient,
    UnitreeCommandOperation,
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
]
