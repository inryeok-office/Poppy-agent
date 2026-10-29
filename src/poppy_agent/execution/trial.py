"""Process-lifetime budget guard for a controlled physical TURN trial.

The guard is pure and hardware-free.  It admits a whole command program before
any dispatch, debits the budget up front (a failed attempt is never refunded,
so it cannot be retried), and locks permanently after an unknown outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock

from poppy_agent.command import CommandType, HighLevelCommandProgram, TurnParameters
from poppy_agent.config.physical_trial import PhysicalTrialSettings
from poppy_agent.execution.readiness import (
    PhysicalCommandClientKind,
    PhysicalReadinessEvidence,
)

_NON_PHYSICAL_COMMANDS = frozenset({CommandType.WAIT, CommandType.STOP})


class TrialGuardError(RuntimeError):
    """Raised when a program is outside the controlled trial budget."""


class TrialGuardState(StrEnum):
    AVAILABLE = "AVAILABLE"
    EXECUTING = "EXECUTING"
    EXHAUSTED = "EXHAUSTED"
    LOCKED = "LOCKED"


@dataclass(frozen=True, slots=True)
class TrialBudgetSnapshot:
    """Secret-free trial accounting for logs and the local status file."""

    state: TrialGuardState
    commands_used: int
    commands_max: int
    turn_degrees_used: float
    turn_degrees_max: float
    motion_seconds_used: float
    motion_seconds_max: float
    lock_reason: str | None
    approval_ref: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "commandsUsed": self.commands_used,
            "commandsMax": self.commands_max,
            "turnDegreesUsed": self.turn_degrees_used,
            "turnDegreesMax": self.turn_degrees_max,
            "motionSecondsUsed": self.motion_seconds_used,
            "motionSecondsMax": self.motion_seconds_max,
            "lockReason": self.lock_reason,
            "approvalRef": self.approval_ref,
        }


class TrialGuard:
    """Thread-safe controlled trial budget that lives as long as the process."""

    def __init__(
        self,
        settings: PhysicalTrialSettings,
        *,
        telemetry_fresh: Callable[[], bool],
    ) -> None:
        self._settings = settings
        self._telemetry_fresh = telemetry_fresh
        self._lock = Lock()
        self._commands_used = 0
        self._turn_degrees_used = 0.0
        self._motion_seconds_used = 0.0
        self._executing = False
        self._lock_reason: str | None = None

    @property
    def settings(self) -> PhysicalTrialSettings:
        return self._settings

    def admit(self, program: HighLevelCommandProgram) -> None:
        """Validate the whole program and debit its budget before any dispatch."""
        turns: list[float] = []
        for command in program.commands:
            if command.type in _NON_PHYSICAL_COMMANDS:
                continue
            if command.type is not CommandType.TURN:
                raise TrialGuardError(
                    f"{command.type.value} is not allowed in the controlled TURN trial"
                )
            if not isinstance(command.parameters, TurnParameters):
                raise TrialGuardError("TURN parameters are not typed TurnParameters")
            angle = command.parameters.angle_degrees
            if angle > self._settings.max_turn_degrees_per_command:
                raise TrialGuardError("TURN angle exceeds the per-command trial limit")
            turns.append(angle)

        program_degrees = sum(turns)
        program_seconds = program_degrees / self._settings.turn_rate_degrees_per_second
        with self._lock:
            if self._lock_reason is not None:
                raise TrialGuardError("controlled trial is locked after an unknown outcome")
            if self._executing:
                raise TrialGuardError("a controlled trial execution is already in progress")
            if self._commands_used + len(turns) > self._settings.max_commands:
                raise TrialGuardError("controlled trial command budget is exhausted")
            if self._turn_degrees_used + program_degrees > self._settings.max_total_turn_degrees:
                raise TrialGuardError("controlled trial total TURN angle would be exceeded")
            if self._motion_seconds_used + program_seconds > self._settings.max_total_seconds:
                raise TrialGuardError("controlled trial total motion time would be exceeded")
            if turns and self._telemetry_fresh() is not True:
                raise TrialGuardError("Robot telemetry is not fresh")
            self._commands_used += len(turns)
            self._turn_degrees_used += program_degrees
            self._motion_seconds_used += program_seconds
            self._executing = True

    def release(self) -> None:
        """End the admitted execution; the debited budget is never refunded."""
        with self._lock:
            self._executing = False

    def lock(self, reason: str) -> None:
        """Reject every further physical command until the process restarts."""
        with self._lock:
            if self._lock_reason is None:
                self._lock_reason = reason

    def available(self) -> bool:
        """Return whether a new single TURN could be admitted right now."""
        return self.snapshot().state is TrialGuardState.AVAILABLE

    def snapshot(self) -> TrialBudgetSnapshot:
        with self._lock:
            if self._lock_reason is not None:
                state = TrialGuardState.LOCKED
            elif self._executing:
                state = TrialGuardState.EXECUTING
            elif (
                self._commands_used >= self._settings.max_commands
                or self._turn_degrees_used >= self._settings.max_total_turn_degrees
                or self._motion_seconds_used >= self._settings.max_total_seconds
            ):
                state = TrialGuardState.EXHAUSTED
            else:
                state = TrialGuardState.AVAILABLE
            return TrialBudgetSnapshot(
                state=state,
                commands_used=self._commands_used,
                commands_max=self._settings.max_commands,
                turn_degrees_used=self._turn_degrees_used,
                turn_degrees_max=self._settings.max_total_turn_degrees,
                motion_seconds_used=self._motion_seconds_used,
                motion_seconds_max=self._settings.max_total_seconds,
                lock_reason=self._lock_reason,
                approval_ref=self._settings.approval_ref,
            )


def controlled_trial_readiness_evidence(
    settings: PhysicalTrialSettings,
    *,
    command_client_kind: PhysicalCommandClientKind,
) -> PhysicalReadinessEvidence:
    """Build readiness evidence only from validated trial configuration.

    ``telemetry_requirements_met`` records that a freshness check is wired;
    freshness itself is enforced at admission time and in operational status.
    ``hardware_validation_completed`` stays false: the explicit trial budget
    replaces it for this first validation run only.
    """
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
        controlled_trial_budget_defined=settings.max_commands >= 1,
    )


__all__ = [
    "TrialBudgetSnapshot",
    "TrialGuard",
    "TrialGuardError",
    "TrialGuardState",
    "controlled_trial_readiness_evidence",
]
