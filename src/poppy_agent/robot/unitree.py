"""Official Unitree SDK2 Python read-only adapter for Go2 state telemetry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from threading import RLock
from typing import Any

from poppy_agent.robot.adapter import RobotIdentity, RobotStatus


class UnitreeSdkUnavailableError(ImportError):
    """Raised when the optional official Unitree SDK is not installed."""


@dataclass(frozen=True, slots=True)
class UnitreeGo2Config:
    """Explicit SDK network and identity configuration."""

    network_interface: str
    identity: RobotIdentity

    def __post_init__(self) -> None:
        if not self.network_interface.strip():
            raise ValueError("network_interface must be explicit")


class UnitreeGo2Adapter:
    """Subscribe to official Go2 `rt/lowstate` without publishing commands."""

    def __init__(self, config: UnitreeGo2Config) -> None:
        self._config = config
        self._subscriber: object | None = None
        self._initialized = False
        self._state_received = False
        self._lock = RLock()

    def initialize(self) -> None:
        """Initialize DDS and subscribe to the official Go2 low-state topic."""
        if self._initialized:
            return
        channel_factory_initialize, channel_subscriber, low_state_type = _load_sdk()
        channel_factory_initialize(0, self._config.network_interface)
        subscriber = channel_subscriber("rt/lowstate", low_state_type)
        subscriber.Init(self._handle_state, 10)
        self._subscriber = subscriber
        self._initialized = True

    def identity(self) -> RobotIdentity:
        self._require_initialized()
        return self._config.identity

    def status(self) -> RobotStatus:
        self._require_initialized()
        with self._lock:
            connection_status = "ONLINE" if self._state_received else "OFFLINE"
        return RobotStatus(
            connection_status=connection_status,
            operational_status="UNAVAILABLE",
            battery_percent=None,
            current_execution_id=None,
        )

    def capabilities(self) -> tuple[str, ...]:
        self._require_initialized()
        return ("telemetry",)

    def shutdown(self) -> None:
        """Close only the read-only subscriber; no SDK command is sent."""
        subscriber = self._subscriber
        if subscriber is not None:
            close = getattr(subscriber, "Close", None)
            if callable(close):
                close()
        self._subscriber = None
        self._initialized = False

    def _handle_state(self, _message: object) -> None:
        with self._lock:
            self._state_received = True

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("UnitreeGo2Adapter is not initialized")


def _load_sdk() -> tuple[Callable[[int, str], Any], Any, Any]:
    try:
        channel = import_module("unitree_sdk2py.core.channel")
        dds = import_module("unitree_sdk2py.idl.unitree_go.msg.dds_")
        return channel.ChannelFactoryInitialize, channel.ChannelSubscriber, dds.LowState_
    except (ImportError, AttributeError) as exc:
        raise UnitreeSdkUnavailableError(
            "Install the official unitree_sdk2_python package and CycloneDDS before "
            "initializing UnitreeGo2Adapter"
        ) from exc
