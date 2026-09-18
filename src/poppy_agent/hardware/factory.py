"""Physical executor construction guarded by the readiness gate."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from poppy_agent.execution.executor import MockExecutionExecutor
from poppy_agent.execution.motion import MotionExecutionStrategy, MotionSleeper
from poppy_agent.execution.readiness import (
    PhysicalExecutionGate,
    PhysicalReadinessEvidence,
)
from poppy_agent.execution.safety import CommandSafetyPolicy

from .boundary import HardwareCommandTarget
from .unitree import UnitreeCommandBackend, UnitreeCommandClient
from .unitree_sdk import UnitreeSdkCommandClient


def create_unitree_execution_executor(
    *,
    robot_id: UUID,
    physical_execution_enabled: bool,
    evidence: PhysicalReadinessEvidence | None = None,
    client_factory: Callable[[], UnitreeCommandClient] | None = None,
    network_interface: str | None = None,
    motion_strategy: MotionExecutionStrategy | None = None,
    sleeper: MotionSleeper | None = None,
) -> MockExecutionExecutor:
    """Create a Unitree-shaped executor only after the readiness gate passes.

    The gate is deliberately evaluated before ``client_factory`` is called, so
    a blocked runtime cannot construct or initialize an SDK transport.
    """
    PhysicalExecutionGate().require_ready(
        physical_execution_enabled=physical_execution_enabled,
        evidence=evidence,
    )
    client = (
        client_factory()
        if client_factory is not None
        else UnitreeSdkCommandClient(network_interface=network_interface)
    )
    backend = UnitreeCommandBackend(
        client,
        motion_strategy=motion_strategy,
        sleeper=sleeper,
    )
    target = HardwareCommandTarget(backend)
    try:
        target.initialize()
    except Exception:
        try:
            target.shutdown()
        except Exception:
            pass
        raise
    return MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=robot_id,
    )


__all__ = ["create_unitree_execution_executor"]
