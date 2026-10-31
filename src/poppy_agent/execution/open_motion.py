"""Per-Execution guard for the time-boxed ``controlled_motion_open`` trial.

Every Execution is checked as a whole before any dispatch: per-command limits,
the planned position inside the arena, total planned motion time, the posture
order (no MOVE, TURN or PRESET after SIT until STAND), the PRESET allow-list and
the approval expiry.  Position is dead reckoned from the configured start pose
for each Execution; there is no localization, so the Robot must be back at that
pose before every Execution.  There is no process budget; a failed or unknown
outcome fails only that Execution and is recorded, never retried.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import Lock

from poppy_agent.command import (
    CommandType,
    HighLevelCommandProgram,
    MoveDirection,
    MoveParameters,
    Posture,
    PostureParameters,
    PresetParameters,
    TurnDirection,
    TurnParameters,
    WaitParameters,
)
from poppy_agent.config.open_motion import OpenMotionSettings
from poppy_agent.execution.readiness import (
    PhysicalCommandClientKind,
    PhysicalReadinessEvidence,
)


class OpenMotionGuardError(RuntimeError):
    """Raised when an Execution is outside the open trial limits."""


class OpenMotionGuardState(StrEnum):
    AVAILABLE = "AVAILABLE"
    EXECUTING = "EXECUTING"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class OpenMotionPlanSummary:
    """Planned totals for one admitted Execution."""

    physical_commands: int
    move_meters: float
    motion_seconds: float


class OpenMotionGuard:
    """Thread-safe per-Execution admission with process-level posture tracking."""

    def __init__(
        self,
        settings: OpenMotionSettings,
        *,
        telemetry_fresh: Callable[[], bool],
        now: Callable[[], datetime],
    ) -> None:
        self._settings = settings
        self._telemetry_fresh = telemetry_fresh
        self._now = now
        self._lock = Lock()
        self._executing = False
        # The Robot is checked standing before the trial; SIT is tracked across
        # Executions because the physical posture persists between them.
        self._sitting = False
        self._executions_admitted = 0
        self._last_failure: str | None = None
        self._last_plan: OpenMotionPlanSummary | None = None

    @property
    def settings(self) -> OpenMotionSettings:
        return self._settings

    def expired(self) -> bool:
        return self._now() >= self._settings.expires_at

    def plan(self, program: HighLevelCommandProgram, *, sitting: bool) -> OpenMotionPlanSummary:
        """Check the whole program without side effects."""
        settings = self._settings
        physical = 0
        move_meters = 0.0
        seconds = 0.0
        x = settings.start_x_meters
        y = settings.start_y_meters
        heading = settings.start_heading_degrees
        for command in program.commands:
            parameters = command.parameters
            if command.type is CommandType.STOP:
                break
            if command.type is CommandType.WAIT:
                if not isinstance(parameters, WaitParameters):
                    raise OpenMotionGuardError("WAIT parameters are not typed")
                seconds += parameters.duration_seconds
                continue
            if command.type.value not in settings.allowed_commands:
                raise OpenMotionGuardError(f"{command.type.value} is not allowed in this trial")
            physical += 1
            if command.type is CommandType.MOVE:
                if not isinstance(parameters, MoveParameters):
                    raise OpenMotionGuardError("MOVE parameters are not typed")
                if sitting:
                    raise OpenMotionGuardError("MOVE is not allowed after SIT until STAND")
                if parameters.distance_meters > settings.max_move_meters_per_command:
                    raise OpenMotionGuardError("MOVE distance exceeds the per-command limit")
                move_meters += parameters.distance_meters
                sign = 1.0 if parameters.direction is MoveDirection.FORWARD else -1.0
                x += sign * parameters.distance_meters * math.sin(math.radians(heading))
                y += sign * parameters.distance_meters * math.cos(math.radians(heading))
                # The allowed area is convex and each segment starts inside it, so an
                # end point inside means the whole segment is inside.
                if not self._inside_arena(x, y):
                    raise OpenMotionGuardError("MOVE leaves the arena")
                seconds += parameters.distance_meters / settings.linear_speed_meters_per_second
            elif command.type is CommandType.TURN:
                if not isinstance(parameters, TurnParameters):
                    raise OpenMotionGuardError("TURN parameters are not typed")
                if sitting:
                    raise OpenMotionGuardError("TURN is not allowed after SIT until STAND")
                if parameters.angle_degrees > settings.max_turn_degrees_per_command:
                    raise OpenMotionGuardError("TURN angle exceeds the per-command limit")
                heading += (
                    parameters.angle_degrees
                    if parameters.direction is TurnDirection.RIGHT
                    else -parameters.angle_degrees
                )
                seconds += parameters.angle_degrees / settings.turn_rate_degrees_per_second
            elif command.type is CommandType.POSTURE:
                if not isinstance(parameters, PostureParameters):
                    raise OpenMotionGuardError("POSTURE parameters are not typed")
                sitting = parameters.posture is Posture.SIT
                seconds += settings.posture_settle_seconds
            elif command.type is CommandType.PRESET:
                if not isinstance(parameters, PresetParameters):
                    raise OpenMotionGuardError("PRESET parameters are not typed")
                if sitting:
                    raise OpenMotionGuardError("PRESET is not allowed after SIT until STAND")
                if parameters.preset_code not in settings.allowed_presets:
                    raise OpenMotionGuardError("PRESET code is not allow-listed")
                seconds += settings.preset_settle_seconds
            else:
                raise OpenMotionGuardError(f"{command.type.value} is not supported")
        if seconds > settings.max_total_seconds + 1e-9:
            raise OpenMotionGuardError("total motion time exceeds the per-Execution limit")
        return OpenMotionPlanSummary(physical, move_meters, seconds)

    def _inside_arena(self, x: float, y: float) -> bool:
        settings = self._settings
        margin = settings.arena_margin_meters
        return (
            margin - 1e-9 <= x <= settings.arena_width_meters - margin + 1e-9
            and margin - 1e-9 <= y <= settings.arena_depth_meters - margin + 1e-9
        )

    def admit(self, program: HighLevelCommandProgram) -> None:
        """Validate the whole Execution before dispatch; reject on any limit."""
        with self._lock:
            if self.expired():
                raise OpenMotionGuardError("the open trial approval window has expired")
            if self._executing:
                raise OpenMotionGuardError("an Execution is already in progress")
            summary = self.plan(program, sitting=self._sitting)
            if summary.physical_commands and self._telemetry_fresh() is not True:
                raise OpenMotionGuardError("Robot telemetry is not fresh")
            self._executing = True
            self._executions_admitted += 1
            self._last_plan = summary

    def release(self) -> None:
        with self._lock:
            self._executing = False

    def lock(self, reason: str) -> None:
        """Record an unknown outcome; only that Execution fails in this mode."""
        with self._lock:
            self._last_failure = reason

    def note_sit_requested(self) -> None:
        """Assume SIT from the moment it is sent, even if its result is unknown."""
        with self._lock:
            self._sitting = True

    def sitting(self) -> bool:
        with self._lock:
            return self._sitting

    def note_stand_completed(self) -> None:
        with self._lock:
            self._sitting = False

    def available(self) -> bool:
        return self.state() is OpenMotionGuardState.AVAILABLE

    def state(self) -> OpenMotionGuardState:
        if self.expired():
            return OpenMotionGuardState.EXPIRED
        with self._lock:
            return (
                OpenMotionGuardState.EXECUTING
                if self._executing
                else OpenMotionGuardState.AVAILABLE
            )

    def snapshot(self) -> dict[str, object]:
        state = self.state()
        with self._lock:
            plan = self._last_plan
            return {
                "state": state.value,
                "sitting": self._sitting,
                "executionsAdmitted": self._executions_admitted,
                "lastFailure": self._last_failure,
                "lastPlan": None
                if plan is None
                else {
                    "physicalCommands": plan.physical_commands,
                    "moveMeters": plan.move_meters,
                    "motionSeconds": plan.motion_seconds,
                },
                "expiresAt": self._settings.expires_at.isoformat(),
                "approvalRef": self._settings.approval_ref,
            }


def open_motion_readiness_evidence(
    settings: OpenMotionSettings,
    *,
    command_client_kind: PhysicalCommandClientKind,
) -> PhysicalReadinessEvidence:
    """Build readiness evidence only from validated open trial configuration."""
    approved = bool(settings.approval_ref)
    return PhysicalReadinessEvidence(
        command_client_kind=command_client_kind,
        production_motion_profile_approved=approved,
        physical_limits_defined=True,
        preset_policy_defined=True,
        emergency_procedure_confirmed=approved,
        telemetry_requirements_met=True,
        observability_requirements_met=True,
        equipment_owner_approved=approved,
        hardware_validation_completed=False,
        controlled_trial_budget_defined=True,
    )


__all__ = [
    "OpenMotionGuard",
    "OpenMotionGuardError",
    "OpenMotionGuardState",
    "OpenMotionPlanSummary",
    "open_motion_readiness_evidence",
]
