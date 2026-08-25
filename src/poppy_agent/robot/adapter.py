"""Minimal read-only RobotAdapter contract for the Agent core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RobotIdentity:
    """Stable robot metadata exposed by an adapter."""

    robot_id: str
    model: str
    edition: str
    firmware_version: str
    sdk_version: str


@dataclass(frozen=True, slots=True)
class RobotStatus:
    """Read-only robot state exposed by an adapter."""

    connection_status: str
    operational_status: str
    battery_percent: int | None
    current_execution_id: str | None


class RobotAdapter(Protocol):
    """Minimum lifecycle and telemetry contract required by the Agent."""

    def initialize(self) -> None:
        """Initialize the adapter connection or subscription."""

    def identity(self) -> RobotIdentity:
        """Return robot metadata after initialization."""

    def status(self) -> RobotStatus:
        """Return the current read-only robot state."""

    def capabilities(self) -> tuple[str, ...]:
        """Return capabilities confirmed by this adapter."""

    def shutdown(self) -> None:
        """Release adapter resources without issuing robot control commands."""
