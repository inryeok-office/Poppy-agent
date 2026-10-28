"""Physical executor construction guarded by the readiness gate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from poppy_agent.config.physical_trial import PhysicalTrialSettings
from poppy_agent.execution.executor import MockExecutionExecutor
from poppy_agent.execution.motion import MotionExecutionStrategy, MotionProfile, MotionSleeper
from poppy_agent.execution.readiness import (
    PhysicalCommandClientKind,
    PhysicalExecutionGate,
    PhysicalReadinessEvidence,
)
from poppy_agent.execution.safety import CommandSafetyPolicy
from poppy_agent.execution.trial import TrialGuard, controlled_trial_readiness_evidence

from .boundary import HardwareCommandTarget
from .unitree import UnitreeCommandBackend, UnitreeCommandClient
from .unitree_sdk import Go2TurnRateMapper, MotionStreamTiming, UnitreeSdkCommandClient


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


@dataclass(frozen=True, slots=True)
class ControlledTrialExecution:
    """Executor and the process-lifetime trial guard that limits it."""

    executor: MockExecutionExecutor
    guard: TrialGuard


def create_controlled_trial_executor(
    *,
    robot_id: UUID,
    physical_execution_enabled: bool,
    trial_settings: PhysicalTrialSettings | None,
    telemetry_fresh: Callable[[], bool],
    network_interface: str | None = None,
    sport_client_factory: Callable[[], object] | None = None,
    timing: MotionStreamTiming | None = None,
) -> ControlledTrialExecution:
    """Create the TURN-only trial executor after the readiness gate passes.

    Evidence is derived only from validated ``trial_settings``; callers cannot
    inject it.  The gate runs before any SDK object is constructed.
    ``sport_client_factory`` and ``timing`` are test seams for an inert
    SportClient double and a fake clock; production passes neither.
    """
    evidence = (
        controlled_trial_readiness_evidence(
            trial_settings, command_client_kind=PhysicalCommandClientKind.REAL
        )
        if trial_settings is not None
        else None
    )
    PhysicalExecutionGate().require_ready(
        physical_execution_enabled=physical_execution_enabled,
        evidence=evidence,
    )
    assert trial_settings is not None
    guard = TrialGuard(trial_settings, telemetry_fresh=telemetry_fresh)
    client = UnitreeSdkCommandClient(
        sdk_client_factory=sport_client_factory,
        network_interface=network_interface,
        motion_mapper=Go2TurnRateMapper(trial_settings.turn_left_yaw_sign),
        timing=timing,
    )
    backend = UnitreeCommandBackend(
        client,
        motion_strategy=MotionExecutionStrategy(
            MotionProfile(
                linear_rate_meters_per_second=None,
                angular_rate_degrees_per_second=trial_settings.turn_rate_degrees_per_second,
            )
        ),
        trial_guard=guard,
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
    executor = MockExecutionExecutor(
        target,
        safety_policy=CommandSafetyPolicy(),
        bound_robot_id=robot_id,
        program_guard=guard,
    )
    return ControlledTrialExecution(executor=executor, guard=guard)


__all__ = [
    "ControlledTrialExecution",
    "create_controlled_trial_executor",
    "create_unitree_execution_executor",
]
