"""Per-Execution guard for the time-boxed ``controlled_motion_open`` trial.

Every Execution is checked as a whole before any dispatch: per-command limits,
total MOVE distance, total planned motion time, the posture order (no MOVE,
TURN or PRESET after SIT until STAND), the PRESET allow-list and the approval
expiry.  There is no process budget; a failed or unknown outcome fails only that
Execution and is recorded, never retried.

Posture is tracked across Executions.  A failed or cancelled POSTURE or PRESET
leaves the physical posture unknown: every physical program is then rejected
until the posture is re-read from the Robot (``posture_probe``) or the Agent is
restarted after an operator has confirmed the Robot is standing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import Lock

from poppy_agent.command import (
    CommandType,
    HighLevelCommandProgram,
    MoveParameters,
    Posture,
    PostureParameters,
    PresetParameters,
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
    POSTURE_UNKNOWN = "POSTURE_UNKNOWN"


class TrackedPosture(StrEnum):
    """The guard's belief about the physical posture between commands."""

    STANDING = "STANDING"
    SITTING = "SITTING"
    UNKNOWN = "UNKNOWN"


POSTURE_UNKNOWN_MESSAGE = (
    "Robot posture is unknown after a failed posture or preset command; "
    "re-read the posture from the Robot, or confirm it is standing and restart the Agent"
)


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
        posture_probe: Callable[[], Posture | None] | None = None,
    ) -> None:
        self._settings = settings
        self._telemetry_fresh = telemetry_fresh
        self._now = now
        self._posture_probe = posture_probe
        self._lock = Lock()
        self._executing = False
        # Without a probe the Robot is checked standing before the trial; with a
        # probe the actual posture is read before the first Execution.  The
        # posture is tracked across Executions because it persists between them.
        self._posture = TrackedPosture.STANDING
        self._posture_unknown_reason: str | None = None
        if posture_probe is not None:
            self._posture = TrackedPosture.UNKNOWN
            self._posture_unknown_reason = "posture not yet read from the Robot"
            self._resync_posture_locked()
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
                seconds += parameters.distance_meters / settings.linear_speed_meters_per_second
            elif command.type is CommandType.TURN:
                if not isinstance(parameters, TurnParameters):
                    raise OpenMotionGuardError("TURN parameters are not typed")
                if sitting:
                    raise OpenMotionGuardError("TURN is not allowed after SIT until STAND")
                if parameters.angle_degrees > settings.max_turn_degrees_per_command:
                    raise OpenMotionGuardError("TURN angle exceeds the per-command limit")
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
        if move_meters > settings.max_total_move_meters + 1e-9:
            raise OpenMotionGuardError("total MOVE distance exceeds the per-Execution limit")
        if seconds > settings.max_total_seconds + 1e-9:
            raise OpenMotionGuardError("total motion time exceeds the per-Execution limit")
        return OpenMotionPlanSummary(physical, move_meters, seconds)

    def admit(self, program: HighLevelCommandProgram) -> None:
        """Validate the whole Execution before dispatch; reject on any limit."""
        with self._lock:
            if self.expired():
                raise OpenMotionGuardError("the open trial approval window has expired")
            if self._executing:
                raise OpenMotionGuardError("an Execution is already in progress")
            if self._posture is TrackedPosture.UNKNOWN:
                self._resync_posture_locked()
            summary = self.plan(program, sitting=self._posture is TrackedPosture.SITTING)
            if summary.physical_commands and self._posture is TrackedPosture.UNKNOWN:
                raise OpenMotionGuardError(POSTURE_UNKNOWN_MESSAGE)
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
        """Assume SIT from the moment it is sent; a failure later makes it unknown."""
        with self._lock:
            self._posture = TrackedPosture.SITTING

    def sitting(self) -> bool:
        with self._lock:
            return self._posture is TrackedPosture.SITTING

    def posture(self) -> TrackedPosture:
        with self._lock:
            return self._posture

    def note_stand_completed(self) -> None:
        with self._lock:
            self._posture = TrackedPosture.STANDING
            self._posture_unknown_reason = None

    def mark_posture_unknown(self, reason: str) -> TrackedPosture:
        """Record a failed posture-changing command and re-read the actual posture.

        The SDK may reject or time out on a command the Robot partly performed,
        so the internal belief is dropped instead of guessed.  Returns the
        posture after the immediate re-read (``UNKNOWN`` without a probe).
        """
        with self._lock:
            self._last_failure = reason
            self._posture = TrackedPosture.UNKNOWN
            self._posture_unknown_reason = reason
            return self._resync_posture_locked()

    def resync_posture(self) -> TrackedPosture:
        """Operator path: replace the tracked posture with the posture read now.

        Only an answer from the Robot can clear ``UNKNOWN``; without a probe, or
        when the probe has no fresh answer, the tracked posture is unchanged.
        """
        with self._lock:
            return self._resync_posture_locked()

    def _resync_posture_locked(self) -> TrackedPosture:
        if self._posture_probe is None:
            return self._posture
        try:
            observed = self._posture_probe()
        except Exception:
            observed = None
        if observed is Posture.SIT:
            self._posture = TrackedPosture.SITTING
            self._posture_unknown_reason = None
        elif observed is Posture.STAND:
            self._posture = TrackedPosture.STANDING
            self._posture_unknown_reason = None
        return self._posture

    def available(self) -> bool:
        return self.state() is OpenMotionGuardState.AVAILABLE

    def state(self) -> OpenMotionGuardState:
        if self.expired():
            return OpenMotionGuardState.EXPIRED
        with self._lock:
            if self._executing:
                return OpenMotionGuardState.EXECUTING
            if self._posture is TrackedPosture.UNKNOWN:
                self._resync_posture_locked()
            if self._posture is TrackedPosture.UNKNOWN:
                return OpenMotionGuardState.POSTURE_UNKNOWN
            return OpenMotionGuardState.AVAILABLE

    def snapshot(self) -> dict[str, object]:
        state = self.state()
        with self._lock:
            plan = self._last_plan
            return {
                "state": state.value,
                "sitting": self._posture is TrackedPosture.SITTING,
                "posture": self._posture.value,
                "postureUnknownReason": self._posture_unknown_reason,
                "postureProbe": self._posture_probe is not None,
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
    "POSTURE_UNKNOWN_MESSAGE",
    "TrackedPosture",
    "open_motion_readiness_evidence",
]
