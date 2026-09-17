"""Deterministic development-only RobotAdapter implementation."""

from __future__ import annotations

from dataclasses import dataclass

from poppy_agent.robot.adapter import RobotIdentity, RobotStatus


class RobotNotInitializedError(RuntimeError):
    """Raised when telemetry is requested before adapter initialization."""


@dataclass(frozen=True, slots=True)
class MockRobotSpec:
    """Explicit values used by a Mock Robot instance."""

    robot_id: str
    model: str = "mock"
    edition: str = "development"
    firmware_version: str = "mock"
    sdk_version: str = "not-applicable"
    battery_percent: int | None = 100
    current_execution_id: str | None = None

    def __post_init__(self) -> None:
        if not self.robot_id.strip():
            raise ValueError("robot_id must not be empty")
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            raise ValueError("battery_percent must be between 0 and 100")


class MockRobotAdapter:
    """Return explicit, deterministic telemetry without contacting hardware."""

    def __init__(self, spec: MockRobotSpec) -> None:
        self._spec = spec
        self._initialized = False

    def initialize(self) -> None:
        self._initialized = True

    def identity(self) -> RobotIdentity:
        self._require_initialized()
        return RobotIdentity(
            robot_id=self._spec.robot_id,
            model=self._spec.model,
            edition=self._spec.edition,
            firmware_version=self._spec.firmware_version,
            sdk_version=self._spec.sdk_version,
        )

    def status(self) -> RobotStatus:
        self._require_initialized()
        return RobotStatus(
            connection_status="ONLINE",
            operational_status="IDLE",
            battery_percent=self._spec.battery_percent,
            current_execution_id=self._spec.current_execution_id,
        )

    def capabilities(self) -> tuple[str, ...]:
        self._require_initialized()
        # These are capability codes advertised by the development fixture. The
        # Server still decides whether each code is VERIFIED for allocation.
        return (
            "telemetry",
            "COMMAND_MOVE",
            "COMMAND_TURN",
            "COMMAND_POSTURE",
            "COMMAND_STOP",
        )

    def shutdown(self) -> None:
        self._initialized = False

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RobotNotInitializedError("MockRobotAdapter is not initialized")
