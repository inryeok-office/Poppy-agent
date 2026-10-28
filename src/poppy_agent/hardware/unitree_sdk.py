"""Optional Unitree SDK command adapter behind the Poppy hardware boundary.

The SDK is imported lazily and only when an explicitly gated client is
initialized.  This module is safe to import in Mock mode and does not provide
any physical safety approval or motion defaults.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol

from poppy_agent.command import CommandType, MoveDirection, TurnDirection
from poppy_agent.config.open_motion import MAX_LINEAR_SPEED_METERS_PER_SECOND, PRESET_SDK_METHODS
from poppy_agent.config.physical_trial import GO2_MAX_YAW_RATE_RADIANS_PER_SECOND
from poppy_agent.execution.cancellation import (
    ExecutionCancellationToken,
    ExecutionCancelledError,
)
from poppy_agent.execution.motion import MotionPlan, MotionRateUnit, MotionUnit

from .unitree import UnitreeCommandClient


class UnitreeSdkCommandError(RuntimeError):
    """Raised when the optional SDK cannot be initialized or called safely."""


class UnitreeSdkUnavailableError(UnitreeSdkCommandError):
    """Raised when the optional official Unitree SDK is not installed."""


class UnitreeMotionOutcomeUnknownError(UnitreeSdkCommandError):
    """Raised when the Robot may still be moving or the motion result is unknown."""


class UnitreeTurnRateMappingError(ValueError):
    """Raised when a Poppy TURN plan cannot be converted to GO2 yaw rate."""


@dataclass(frozen=True, slots=True)
class UnitreeMotionCommand:
    """Explicit SDK velocity-shaped arguments supplied by a reviewed mapper."""

    vx: float
    vy: float
    vyaw: float

    def __post_init__(self) -> None:
        for value, name in (
            (self.vx, "vx"),
            (self.vy, "vy"),
            (self.vyaw, "vyaw"),
        ):
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")


class UnitreeMotionMapper(Protocol):
    """Map a reviewed Poppy motion plan to explicit SDK arguments."""

    def __call__(self, plan: MotionPlan) -> UnitreeMotionCommand:
        """Return SDK arguments without inventing production defaults."""


_YAW_RATE_FLOAT_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class Go2TurnRateMapper:
    """Map a TURN plan to ``Move(0, 0, vyaw)`` with an explicit LEFT yaw sign.

    ``turn_left_yaw_sign`` comes from configuration because the physical yaw
    direction of a positive SDK value has not been verified by this project.
    """

    turn_left_yaw_sign: int

    def __post_init__(self) -> None:
        if type(self.turn_left_yaw_sign) is not int or self.turn_left_yaw_sign not in (1, -1):
            raise ValueError("turn_left_yaw_sign must be +1 or -1")

    def __call__(self, plan: MotionPlan) -> UnitreeMotionCommand:
        if plan.command_type is not CommandType.TURN:
            raise UnitreeTurnRateMappingError("only TURN plans can map to GO2 yaw rate")
        if plan.magnitude_unit is not MotionUnit.DEGREES:
            raise UnitreeTurnRateMappingError("TURN magnitude must use degrees")
        if plan.rate_unit is not MotionRateUnit.DEGREES_PER_SECOND:
            raise UnitreeTurnRateMappingError("TURN rate must use degrees/second")
        if not isinstance(plan.direction, TurnDirection):
            raise UnitreeTurnRateMappingError("TURN plan must have a typed direction")
        if type(plan.rate) not in (int, float) or not math.isfinite(float(plan.rate)):
            raise UnitreeTurnRateMappingError("TURN rate must be a finite number")
        if plan.rate <= 0:
            raise UnitreeTurnRateMappingError("TURN rate must be positive")
        magnitude = math.radians(float(plan.rate))
        if magnitude > GO2_MAX_YAW_RATE_RADIANS_PER_SECOND + _YAW_RATE_FLOAT_TOLERANCE:
            raise UnitreeTurnRateMappingError("TURN yaw rate exceeds the GO2 0.8 rad/s limit")
        direction = 1 if plan.direction is TurnDirection.LEFT else -1
        return UnitreeMotionCommand(
            vx=0.0, vy=0.0, vyaw=direction * self.turn_left_yaw_sign * magnitude
        )


@dataclass(frozen=True, slots=True)
class Go2MotionMapper:
    """Map MOVE to ``Move(±speed, 0, 0)`` and TURN through :class:`Go2TurnRateMapper`."""

    turn_left_yaw_sign: int

    def __call__(self, plan: MotionPlan) -> UnitreeMotionCommand:
        if plan.command_type is CommandType.TURN:
            return Go2TurnRateMapper(self.turn_left_yaw_sign)(plan)
        if plan.command_type is not CommandType.MOVE:
            raise UnitreeTurnRateMappingError("only MOVE and TURN plans can map to Move")
        if plan.magnitude_unit is not MotionUnit.METERS:
            raise UnitreeTurnRateMappingError("MOVE magnitude must use meters")
        if plan.rate_unit is not MotionRateUnit.METERS_PER_SECOND:
            raise UnitreeTurnRateMappingError("MOVE rate must use meters/second")
        if not isinstance(plan.direction, MoveDirection):
            raise UnitreeTurnRateMappingError("MOVE plan must have a typed direction")
        if type(plan.rate) not in (int, float) or not math.isfinite(float(plan.rate)):
            raise UnitreeTurnRateMappingError("MOVE rate must be a finite number")
        if plan.rate <= 0 or plan.rate > MAX_LINEAR_SPEED_METERS_PER_SECOND:
            raise UnitreeTurnRateMappingError("MOVE speed is outside the approved range")
        direction = 1 if plan.direction is MoveDirection.FORWARD else -1
        return UnitreeMotionCommand(vx=direction * float(plan.rate), vy=0.0, vyaw=0.0)


# Official SDK methods this adapter may call for PRESET; nothing else is reachable.
_PRESET_METHOD_NAMES = frozenset(PRESET_SDK_METHODS.values())


@dataclass(frozen=True, slots=True)
class MotionStreamTiming:
    """Timing for repeated ``Move`` while the expiry behavior is unverified."""

    move_period_seconds: float = 0.05
    max_move_call_seconds: float = 0.5
    stop_move_attempts: int = 3
    stop_move_interval_seconds: float = 0.05
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    # Optional interruptible wait returning whether cancellation was observed;
    # defaults to the token's own wait.  Tests inject a fake-clock wait.
    wait: Callable[[float, ExecutionCancellationToken | None], bool] | None = None


def default_unitree_sport_client_factory(
    network_interface: str | None = None, rpc_timeout_seconds: float | None = None
) -> object:
    """Initialize the official DDS channel and create a Go2 SportClient lazily.

    ``rpc_timeout_seconds`` mirrors the official example's ``SetTimeout(10.0)``
    (example/go2/high_level/go2_sport_client.py:84); the SDK default is 1.0 s.
    """
    if not isinstance(network_interface, str) or not network_interface.strip():
        raise UnitreeSdkCommandError("an explicit Unitree network interface is required")
    try:
        channel = import_module("unitree_sdk2py.core.channel")
        module = import_module("unitree_sdk2py.go2.sport.sport_client")
        channel_factory_initialize = channel.__dict__.get("ChannelFactoryInitialize")
        sport_client = module.__dict__.get("SportClient")
        if not callable(channel_factory_initialize) or not callable(sport_client):
            raise AttributeError("Unitree SDK command symbols are unavailable")
    except (ImportError, AttributeError) as exc:
        raise UnitreeSdkUnavailableError(
            "Install the official unitree_sdk2_python package before enabling the "
            "Unitree command adapter"
        ) from exc
    try:
        channel_factory_initialize(0, network_interface)
        client = sport_client()
        if rpc_timeout_seconds is not None:
            client.SetTimeout(rpc_timeout_seconds)
        return client
    except Exception as exc:
        raise UnitreeSdkCommandError(
            f"Unitree SportClient construction failed: {type(exc).__name__}"
        ) from exc


class UnitreeSdkCommandClient(UnitreeCommandClient):
    """Adapt an injected or lazily-created official SportClient.

    The adapter does not issue ``StopMove`` for Poppy ``STOP``.  STOP is handled
    by the existing program-level executor semantics.  Motion calls require an
    explicit mapper because Poppy distance/angle requests are not SDK velocity
    arguments.
    """

    def __init__(
        self,
        *,
        sdk_client: object | None = None,
        sdk_client_factory: Callable[[], object] | None = None,
        network_interface: str | None = None,
        motion_mapper: UnitreeMotionMapper | None = None,
        timing: MotionStreamTiming | None = None,
        rpc_timeout_seconds: float | None = None,
    ) -> None:
        if sdk_client is not None and sdk_client_factory is not None:
            raise ValueError("provide sdk_client or sdk_client_factory, not both")
        self._sdk_client = sdk_client
        self._client_acquired = sdk_client is not None
        self._sdk_client_factory = sdk_client_factory or (
            lambda: default_unitree_sport_client_factory(network_interface, rpc_timeout_seconds)
        )
        self._motion_mapper = motion_mapper
        self._timing = timing or MotionStreamTiming()
        self.last_motion_trace: MotionStreamTrace | None = None
        self._initialized = False

    @property
    def initialized(self) -> bool:
        """Return whether the underlying SDK object completed initialization."""
        return self._initialized

    def initialize(self) -> None:
        """Construct and initialize the SDK object exactly once."""
        if self._initialized:
            return
        client = self._sdk_client
        if client is None:
            try:
                client = self._sdk_client_factory()
            except UnitreeSdkCommandError:
                raise
            except Exception as exc:
                raise UnitreeSdkCommandError(
                    f"Unitree client factory failed: {type(exc).__name__}"
                ) from exc
            self._sdk_client = client
            self._client_acquired = True
        init = getattr(client, "Init", None)
        if not callable(init):
            raise UnitreeSdkCommandError("Unitree SDK client does not provide Init")
        try:
            result = init()
        except Exception as exc:
            raise UnitreeSdkCommandError(
                f"Unitree SDK initialization failed: {type(exc).__name__}"
            ) from exc
        if result is not None and _normalize_result(result, "Init") is not True:
            raise UnitreeSdkCommandError("Unitree SDK initialization reported failure")
        self._initialized = True

    def sit(self) -> bool:
        """Call the official ``Sit`` operation after initialization."""
        return self._call_operation("Sit")

    def stand_up(self) -> bool:
        """Call the official ``StandUp`` operation after initialization."""
        return self._call_operation("StandUp")

    def balance_stand(self) -> bool:
        """Call the official ``BalanceStand`` operation after initialization."""
        return self._call_operation("BalanceStand")

    def preset(self, method_name: str) -> bool:
        """Call one allow-listed official preset method (Hello, Stretch, Heart, Dance1)."""
        if method_name not in _PRESET_METHOD_NAMES:
            raise UnitreeSdkCommandError("preset method is not allow-listed")
        return self._call_operation(method_name)

    def execute_motion(self, plan: MotionPlan) -> bool:
        """Call ``Move`` only with explicitly supplied SDK-shaped arguments."""
        self._require_initialized()
        if self._motion_mapper is None:
            raise UnitreeSdkCommandError("Move requires an explicit motion mapping policy")
        try:
            command = self._motion_mapper(plan)
        except Exception as exc:
            raise UnitreeSdkCommandError(
                f"Unitree motion mapping failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(command, UnitreeMotionCommand):
            raise UnitreeSdkCommandError("motion mapper returned an invalid command")
        return self._call_operation("Move", command.vx, command.vy, command.vyaw)

    def execute_motion_with_cancellation(
        self,
        plan: MotionPlan,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> bool:
        """Stream ``Move`` for the planned duration, then always attempt ``StopMove``.

        No new ``Move`` starts at or after the planned duration.  A ``Move`` call
        that blocks for ``max_move_call_seconds`` or longer, a ``Move`` failure,
        or a cleanup where no ``StopMove`` succeeded is an unknown outcome.
        """
        self._require_initialized()
        if self._motion_mapper is None:
            raise UnitreeSdkCommandError("Move requires an explicit motion mapping policy")
        try:
            command = self._motion_mapper(plan)
        except Exception as exc:
            raise UnitreeSdkCommandError(
                f"Unitree motion mapping failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(command, UnitreeMotionCommand):
            raise UnitreeSdkCommandError("motion mapper returned an invalid command")

        timing = self._timing
        trace = MotionStreamTrace(command=command, duration_seconds=plan.duration_seconds)
        self.last_motion_trace = trace
        primary_error: BaseException | None = None
        start = timing.monotonic()
        try:
            while True:
                if timing.monotonic() - start >= plan.duration_seconds:
                    break
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                call_started = timing.monotonic()
                try:
                    self._call_operation("Move", command.vx, command.vy, command.vyaw)
                except UnitreeSdkCommandError as exc:
                    raise UnitreeMotionOutcomeUnknownError(
                        "Unitree SDK Move failed during streaming"
                    ) from exc
                trace.move_calls += 1
                if timing.monotonic() - call_started >= timing.max_move_call_seconds:
                    raise UnitreeMotionOutcomeUnknownError("Unitree SDK Move call blocked too long")
                next_send = start + trace.move_calls * timing.move_period_seconds
                wait = min(next_send, start + plan.duration_seconds) - timing.monotonic()
                if wait > 0:
                    if timing.wait is not None:
                        cancelled = timing.wait(wait, cancellation_token)
                    elif cancellation_token is not None:
                        cancelled = cancellation_token.wait(wait)
                    else:
                        timing.sleep(wait)
                        cancelled = False
                    if cancelled and cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            trace.elapsed_seconds = timing.monotonic() - start
            self._stop_move_best_effort(trace)
            # A cancelled motion without a confirmed StopMove is still an unknown outcome.
            if trace.stop_move_successes == 0 and (
                primary_error is None or isinstance(primary_error, ExecutionCancelledError)
            ):
                raise UnitreeMotionOutcomeUnknownError("no StopMove call succeeded after motion")
        return True

    def stop_move(self) -> bool:
        """Call official ``StopMove``; this is not a hardware emergency stop."""
        return self._call_operation("StopMove")

    def _stop_move_best_effort(self, trace: MotionStreamTrace) -> None:
        timing = self._timing
        for attempt in range(timing.stop_move_attempts):
            if attempt:
                timing.sleep(timing.stop_move_interval_seconds)
            trace.stop_move_calls += 1
            try:
                self.stop_move()
            except Exception:
                continue
            trace.stop_move_successes += 1

    def shutdown(self) -> None:
        """Close the SDK object when it exposes a close lifecycle method."""
        if not self._client_acquired:
            return
        client = self._sdk_client
        self._initialized = False
        self._client_acquired = False
        if client is None:
            return
        close = getattr(client, "Close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception as exc:
            raise UnitreeSdkCommandError(
                f"Unitree SDK shutdown failed: {type(exc).__name__}"
            ) from exc

    def _call_operation(self, method_name: str, *args: object) -> bool:
        self._require_initialized()
        client = self._sdk_client
        assert client is not None
        method = getattr(client, method_name, None)
        if not callable(method):
            raise UnitreeSdkCommandError(f"Unitree SDK client does not provide {method_name}")
        try:
            result = method(*args)
        except Exception as exc:
            raise UnitreeSdkCommandError(
                f"Unitree SDK {method_name} failed: {type(exc).__name__}"
            ) from exc
        normalized = _normalize_result(result, method_name)
        if normalized is not True:
            raise UnitreeSdkCommandError(f"Unitree SDK {method_name} reported failure")
        return True

    def _require_initialized(self) -> None:
        if not self._initialized or self._sdk_client is None:
            raise UnitreeSdkCommandError("Unitree SDK command client is not initialized")


@dataclass(slots=True)
class MotionStreamTrace:
    """Secret-free record of the last streamed motion for logs and tests."""

    command: UnitreeMotionCommand
    duration_seconds: float
    move_calls: int = 0
    stop_move_calls: int = 0
    stop_move_successes: int = 0
    elapsed_seconds: float = 0.0


def _normalize_result(result: object, operation: str) -> bool:
    """Normalize SDK bool/int status codes without exposing raw SDK values."""
    if type(result) is bool:
        return result
    if type(result) is int:
        return result == 0
    raise UnitreeSdkCommandError(f"Unitree SDK {operation} returned an unsupported result type")


__all__ = [
    "Go2MotionMapper",
    "Go2TurnRateMapper",
    "MotionStreamTiming",
    "MotionStreamTrace",
    "UnitreeMotionCommand",
    "UnitreeMotionOutcomeUnknownError",
    "UnitreeTurnRateMappingError",
    "UnitreeMotionMapper",
    "UnitreeSdkCommandClient",
    "UnitreeSdkCommandError",
    "UnitreeSdkUnavailableError",
    "default_unitree_sport_client_factory",
]
