"""Official Unitree SDK2 Python read-only adapter for Go2 state telemetry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from threading import RLock
from time import monotonic
from typing import Any

from poppy_agent.robot.adapter import RobotIdentity, RobotStatus


class UnitreeSdkUnavailableError(ImportError):
    """Raised when the optional official Unitree SDK is not installed."""


@dataclass(frozen=True, slots=True)
class UnitreeGo2Config:
    """Explicit SDK network and identity configuration."""

    network_interface: str
    identity: RobotIdentity
    telemetry_stale_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.network_interface.strip():
            raise ValueError("network_interface must be explicit")
        if self.telemetry_stale_timeout_seconds is None:
            raise ValueError("telemetry_stale_timeout_seconds must be explicit")
        if self.telemetry_stale_timeout_seconds <= 0:
            raise ValueError("telemetry_stale_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class UnitreeTelemetrySnapshot:
    """Minimal read-only low-state evidence retained by the adapter.

    ``mode`` remains unset because the installed SDK exposes no documented Go2
    operational-mode field in ``LowState_`` that can safely map to Poppy's
    operational-status contract.
    """

    received_at: datetime
    battery_percent: int | None
    mode: str | None = None


class UnitreeGo2Adapter:
    """Subscribe to official Go2 `rt/lowstate` without publishing commands."""

    def __init__(
        self,
        config: UnitreeGo2Config,
        *,
        monotonic_clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._monotonic_clock = monotonic_clock
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._subscriber: object | None = None
        self._initialized = False
        self._last_received_monotonic: float | None = None
        self._telemetry_snapshot: UnitreeTelemetrySnapshot | None = None
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
            snapshot = self._telemetry_snapshot
            connection_status = "ONLINE" if self._telemetry_is_recent_locked() else "OFFLINE"
        return RobotStatus(
            connection_status=connection_status,
            operational_status="UNAVAILABLE",
            battery_percent=(
                snapshot.battery_percent
                if connection_status == "ONLINE" and snapshot is not None
                else None
            ),
            current_execution_id=None,
        )

    def telemetry_snapshot(self) -> UnitreeTelemetrySnapshot | None:
        """Return the latest read-only snapshot without extending the Server payload."""
        self._require_initialized()
        with self._lock:
            return self._telemetry_snapshot

    def capabilities(self) -> tuple[str, ...]:
        self._require_initialized()
        return ("TELEMETRY",)

    def shutdown(self) -> None:
        """Close only the read-only subscriber; no SDK command is sent."""
        subscriber = self._subscriber
        if subscriber is not None:
            close = getattr(subscriber, "Close", None)
            if callable(close):
                close()
        self._subscriber = None
        self._initialized = False

    def _handle_state(self, message: object) -> None:
        with self._lock:
            self._telemetry_snapshot = UnitreeTelemetrySnapshot(
                received_at=self._utcnow(),
                battery_percent=_battery_percent_from_low_state(message),
            )
            self._last_received_monotonic = self._monotonic_clock()

    def _telemetry_is_recent_locked(self) -> bool:
        if self._last_received_monotonic is None:
            return False
        assert self._config.telemetry_stale_timeout_seconds is not None
        return (
            self._monotonic_clock() - self._last_received_monotonic
            <= self._config.telemetry_stale_timeout_seconds
        )

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


def _battery_percent_from_low_state(message: object) -> int | None:
    """Read the SDK-documented BMS state-of-charge without inferring voltage.

    Invalid or incomplete messages remain telemetry evidence but do not create an
    unverified battery percentage.
    """
    bms_state = getattr(message, "bms_state", None)
    state_of_charge = getattr(bms_state, "soc", None)
    if isinstance(state_of_charge, bool) or not isinstance(state_of_charge, int):
        return None
    if not 0 <= state_of_charge <= 100:
        return None
    return state_of_charge
