"""Unitree-specific command mapping contracts with an inert fake client.

This module deliberately contains no Unitree SDK import.  A future client may
adapt an official SDK object behind :class:`UnitreeCommandClient`, but this
phase only provides the dependency-injected fake implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from poppy_agent.command import CommandType, Posture, PostureParameters
from poppy_agent.execution.motion import MotionExecutionStrategy, MotionPlan, MotionSleeper
from poppy_agent.hardware.boundary import HardwareCommandIntent, HardwareCommandPort


class UnitreeCommandOperation(StrEnum):
    """Official high-level operation names represented by the client contract."""

    SIT = "Sit"
    STAND_UP = "StandUp"
    MOVE = "Move"


class UnitreeCommandClient(Protocol):
    """Small dependency-injection boundary for a future official SDK client."""

    def initialize(self) -> None:
        """Prepare the client without specifying a transport here."""

    def sit(self) -> bool:
        """Represent the official Go2 high-level Sit operation."""

    def stand_up(self) -> bool:
        """Represent the official Go2 high-level StandUp operation."""

    def execute_motion(self, plan: MotionPlan) -> bool:
        """Represent a future SDK Move call after strategy planning."""

    def shutdown(self) -> None:
        """Release client resources."""


class UnitreeCommandBackendError(RuntimeError):
    """Raised when a Unitree mapping is unsupported or cannot be dispatched."""


@dataclass(frozen=True, slots=True)
class FakeUnitreeCall:
    """One recorded high-level operation; no SDK object is retained."""

    operation: UnitreeCommandOperation
    parameters: object | None = None


class FakeUnitreeCommandClient:
    """Inert client double that records posture calls and injects failures."""

    def __init__(
        self,
        *,
        fail_initialize: bool = False,
        fail_operation: UnitreeCommandOperation | None = None,
        operation_result: bool = True,
    ) -> None:
        self._fail_initialize = fail_initialize
        self._fail_operation = fail_operation
        self._operation_result = operation_result
        self._initialized = False
        self.calls: list[FakeUnitreeCall] = []

    @property
    def initialized(self) -> bool:
        """Expose lifecycle state for deterministic tests."""
        return self._initialized

    def initialize(self) -> None:
        """Initialize only in memory."""
        if self._fail_initialize:
            raise UnitreeCommandBackendError(
                "configured fake Unitree client initialization failure"
            )
        self._initialized = True

    def sit(self) -> bool:
        """Record the official Sit-shaped operation without executing it."""
        return self._record(UnitreeCommandOperation.SIT)

    def stand_up(self) -> bool:
        """Record the official StandUp-shaped operation without executing it."""
        return self._record(UnitreeCommandOperation.STAND_UP)

    def execute_motion(self, plan: MotionPlan) -> bool:
        """Record a planned motion without converting or executing it."""
        return self._record(UnitreeCommandOperation.MOVE, plan)

    def shutdown(self) -> None:
        """Shutdown only the in-memory fake client."""
        self._initialized = False

    def _record(
        self,
        operation: UnitreeCommandOperation,
        parameters: object | None = None,
    ) -> bool:
        if not self._initialized:
            raise UnitreeCommandBackendError("fake Unitree client is not initialized")
        if self._fail_operation is operation:
            raise UnitreeCommandBackendError(
                f"configured fake Unitree client failure for {operation.value}"
            )
        self.calls.append(FakeUnitreeCall(operation, parameters))
        return self._operation_result


class UnitreeCommandBackend(HardwareCommandPort):
    """Map only explicitly safe protocol cases to a client abstraction.

    WAIT and program STOP are handled at the execution layer and do not call a
    Unitree client.  Poppy MOVE and TURN are not directly mapped because the
    official high-level operation uses velocity-shaped arguments, while Poppy
    supplies distance and angle semantics.  PRESET is intentionally unsupported.
    """

    _SUPPORTED_COMMANDS = frozenset({CommandType.WAIT, CommandType.POSTURE, CommandType.STOP})

    def __init__(
        self,
        client: UnitreeCommandClient,
        *,
        motion_strategy: MotionExecutionStrategy | None = None,
        sleeper: MotionSleeper | None = None,
    ) -> None:
        self._client = client
        self._motion_strategy = motion_strategy
        self._sleeper = sleeper
        self._initialized = False

    @property
    def initialized(self) -> bool:
        """Expose backend lifecycle state for tests and future wiring."""
        return self._initialized

    def initialize(self) -> None:
        """Initialize the injected client; no SDK is loaded here."""
        self._client.initialize()
        self._initialized = True

    def supports(self, command_type: CommandType) -> bool:
        """Return explicit direct-mapping support only."""
        if command_type in self._SUPPORTED_COMMANDS:
            return True
        return (
            command_type in {CommandType.MOVE, CommandType.TURN}
            and self._motion_strategy is not None
            and self._motion_strategy.configured
            and self._sleeper is not None
        )

    def preflight(self, intent: HardwareCommandIntent) -> None:
        """Plan motion commands before the executor dispatches any command."""
        if intent.type in {CommandType.MOVE, CommandType.TURN}:
            if not self.supports(intent.type):
                raise UnitreeCommandBackendError(
                    f"Unitree command mapping is unsupported for {intent.type.value}"
                )
            assert self._motion_strategy is not None
            self._motion_strategy.plan(intent)

    def dispatch(self, intent: HardwareCommandIntent) -> bool:
        """Dispatch an intent to the client or reject it without fallback."""
        if not self._initialized:
            raise UnitreeCommandBackendError("Unitree command backend is not initialized")
        if not self.supports(intent.type):
            raise UnitreeCommandBackendError(
                f"Unitree command mapping is unsupported for {intent.type.value}"
            )
        if intent.type is CommandType.WAIT:
            return False
        if intent.type is CommandType.STOP:
            return True
        if intent.type in {CommandType.MOVE, CommandType.TURN}:
            if self._motion_strategy is None or self._sleeper is None:
                raise UnitreeCommandBackendError(
                    f"Unitree command mapping is unsupported for {intent.type.value}"
                )
            plan = self._motion_strategy.plan(intent)
            result = self._client.execute_motion(plan)
            if result is not True:
                raise UnitreeCommandBackendError(
                    f"Unitree client reported failure for {intent.type.value}"
                )
            self._sleeper.sleep(plan.duration_seconds)
            return False
        if not isinstance(intent.parameters, PostureParameters):
            raise UnitreeCommandBackendError("POSTURE intent does not have typed parameters")
        if intent.parameters.posture is Posture.SIT:
            result = self._client.sit()
        else:
            result = self._client.stand_up()
        if result is not True:
            raise UnitreeCommandBackendError(
                f"Unitree client reported failure for {intent.parameters.posture.value}"
            )
        return False

    def shutdown(self) -> None:
        """Shutdown the injected client without synthesizing a stop command."""
        try:
            self._client.shutdown()
        finally:
            self._initialized = False


__all__ = [
    "FakeUnitreeCall",
    "FakeUnitreeCommandClient",
    "UnitreeCommandBackend",
    "UnitreeCommandBackendError",
    "UnitreeCommandClient",
    "UnitreeCommandOperation",
]
