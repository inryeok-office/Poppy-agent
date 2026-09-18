"""Optional Unitree SDK command adapter behind the Poppy hardware boundary.

The SDK is imported lazily and only when an explicitly gated client is
initialized.  This module is safe to import in Mock mode and does not provide
any physical safety approval or motion defaults.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol

from poppy_agent.execution.motion import MotionPlan

from .unitree import UnitreeCommandClient


class UnitreeSdkCommandError(RuntimeError):
    """Raised when the optional SDK cannot be initialized or called safely."""


class UnitreeSdkUnavailableError(UnitreeSdkCommandError):
    """Raised when the optional official Unitree SDK is not installed."""


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


def default_unitree_sport_client_factory(network_interface: str | None = None) -> object:
    """Initialize the official DDS channel and create a Go2 SportClient lazily."""
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
        return sport_client()
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
    ) -> None:
        if sdk_client is not None and sdk_client_factory is not None:
            raise ValueError("provide sdk_client or sdk_client_factory, not both")
        self._sdk_client = sdk_client
        self._sdk_client_factory = sdk_client_factory or (
            lambda: default_unitree_sport_client_factory(network_interface)
        )
        self._motion_mapper = motion_mapper
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
        self._sdk_client = client
        self._initialized = True

    def sit(self) -> bool:
        """Call the official ``Sit`` operation after initialization."""
        return self._call_operation("Sit")

    def stand_up(self) -> bool:
        """Call the official ``StandUp`` operation after initialization."""
        return self._call_operation("StandUp")

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

    def shutdown(self) -> None:
        """Close the SDK object when it exposes a close lifecycle method."""
        if not self._initialized:
            return
        client = self._sdk_client
        self._initialized = False
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


def _normalize_result(result: object, operation: str) -> bool:
    """Normalize SDK bool/int status codes without exposing raw SDK values."""
    if type(result) is bool:
        return result
    if type(result) is int:
        return result == 0
    raise UnitreeSdkCommandError(f"Unitree SDK {operation} returned an unsupported result type")


__all__ = [
    "UnitreeMotionCommand",
    "UnitreeMotionMapper",
    "UnitreeSdkCommandClient",
    "UnitreeSdkCommandError",
    "UnitreeSdkUnavailableError",
    "default_unitree_sport_client_factory",
]
