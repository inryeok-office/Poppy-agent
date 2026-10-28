"""Unitree-specific command mapping contracts with an inert fake client.

This module deliberately contains no Unitree SDK import.  A future client may
adapt an official SDK object behind :class:`UnitreeCommandClient`, but this
phase only provides the dependency-injected fake implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from poppy_agent.command import CommandType, Posture, PostureParameters
from poppy_agent.execution.cancellation import (
    ExecutionCancellationToken,
    ExecutionCancelledError,
)
from poppy_agent.execution.motion import MotionExecutionStrategy, MotionPlan, MotionSleeper
from poppy_agent.hardware.boundary import HardwareCommandIntent, HardwareCommandPort
from poppy_agent.observability import (
    EXECUTION_PHYSICAL_TRIAL_LOCKED,
    EXECUTION_PHYSICAL_TURN_FINISHED,
    EXECUTION_PHYSICAL_TURN_STARTED,
    log_event,
    safe_exception_type,
)

if TYPE_CHECKING:
    from poppy_agent.execution.trial import TrialGuard

logger = logging.getLogger(__name__)


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


class StreamingMotion(Protocol):
    """Client method that streams a planned motion and owns its duration."""

    def __call__(
        self, plan: MotionPlan, cancellation_token: ExecutionCancellationToken | None
    ) -> bool:
        """Execute the full planned motion, honoring cancellation."""


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
        trial_guard: TrialGuard | None = None,
    ) -> None:
        self._client = client
        self._motion_strategy = motion_strategy
        self._sleeper = sleeper
        self._trial_guard = trial_guard
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
            and (self._sleeper is not None or self._streaming_motion is not None)
        )

    @property
    def _streaming_motion(self) -> StreamingMotion | None:
        """Return a client method that owns motion timing, when provided."""
        method = getattr(self._client, "execute_motion_with_cancellation", None)
        return method if callable(method) else None

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
        return self._dispatch(intent, None)

    def dispatch_with_cancellation(
        self, intent: HardwareCommandIntent, cancellation_token: ExecutionCancellationToken
    ) -> bool:
        """Dispatch while allowing a planned wait to be interrupted."""
        cancellation_token.raise_if_cancelled()
        return self._dispatch(intent, cancellation_token)

    def _dispatch(
        self,
        intent: HardwareCommandIntent,
        cancellation_token: ExecutionCancellationToken | None,
    ) -> bool:
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
            # An injected sleeper keeps the legacy single-call timing; otherwise
            # the client must stream the motion and own its duration.
            streaming = self._streaming_motion if self._sleeper is None else None
            if self._motion_strategy is not None and streaming is not None:
                self._dispatch_streaming_motion(
                    self._motion_strategy.plan(intent), streaming, cancellation_token
                )
                return False
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
            self._sleeper.sleep(plan.duration_seconds, cancellation_token)
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

    def _dispatch_streaming_motion(
        self,
        plan: MotionPlan,
        streaming: StreamingMotion,
        cancellation_token: ExecutionCancellationToken | None,
    ) -> None:
        """Let the client own the motion duration; lock the trial on unknown outcomes."""
        trial = self._trial_guard.snapshot() if self._trial_guard is not None else None
        log_event(
            logger,
            logging.INFO,
            EXECUTION_PHYSICAL_TURN_STARTED,
            command_type=plan.command_type.value,
            direction=plan.direction.value,
            angle_degrees=plan.magnitude,
            duration_seconds=plan.duration_seconds,
            trial_state=trial.state.value if trial is not None else None,
            trial_commands_used=trial.commands_used if trial is not None else None,
            trial_commands_max=trial.commands_max if trial is not None else None,
            approval_ref=trial.approval_ref if trial is not None else None,
        )
        try:
            result = streaming(plan, cancellation_token)
            if result is not True:
                raise UnitreeCommandBackendError(
                    f"Unitree client reported failure for {plan.command_type.value}"
                )
        except ExecutionCancelledError:
            self._log_motion_finished(plan, "CANCELLED")
            raise
        except Exception as exc:
            if self._trial_guard is not None:
                self._trial_guard.lock(f"{plan.command_type.value} outcome unknown")
                log_event(
                    logger,
                    logging.ERROR,
                    EXECUTION_PHYSICAL_TRIAL_LOCKED,
                    command_type=plan.command_type.value,
                    error_type=safe_exception_type(exc),
                )
            self._log_motion_finished(plan, "FAILED")
            raise
        self._log_motion_finished(plan, "COMPLETED")

    def _log_motion_finished(self, plan: MotionPlan, status: str) -> None:
        trace = getattr(self._client, "last_motion_trace", None)
        trial = self._trial_guard.snapshot() if self._trial_guard is not None else None
        command = getattr(trace, "command", None)
        log_event(
            logger,
            logging.INFO if status != "FAILED" else logging.ERROR,
            EXECUTION_PHYSICAL_TURN_FINISHED,
            execution_status=status,
            command_type=plan.command_type.value,
            direction=plan.direction.value,
            angle_degrees=plan.magnitude,
            vyaw=getattr(command, "vyaw", None),
            duration_seconds=plan.duration_seconds,
            elapsed_seconds=getattr(trace, "elapsed_seconds", None),
            move_calls=getattr(trace, "move_calls", None),
            stop_move_calls=getattr(trace, "stop_move_calls", None),
            stop_move_successes=getattr(trace, "stop_move_successes", None),
            trial_state=trial.state.value if trial is not None else None,
            trial_commands_used=trial.commands_used if trial is not None else None,
            trial_commands_max=trial.commands_max if trial is not None else None,
            approval_ref=trial.approval_ref if trial is not None else None,
        )

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
