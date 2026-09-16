"""Fail-closed readiness evaluation for future physical execution."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum


class PhysicalReadinessStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class PhysicalReadinessBlocker(StrEnum):
    """Conditions that must be resolved before physical execution is allowed."""

    PHYSICAL_EXECUTION_DISABLED = "PHYSICAL_EXECUTION_DISABLED"
    REAL_COMMAND_CLIENT_MISSING = "REAL_COMMAND_CLIENT_MISSING"
    PRODUCTION_MOTION_PROFILE_UNAPPROVED = "PRODUCTION_MOTION_PROFILE_UNAPPROVED"
    PHYSICAL_LIMITS_UNDEFINED = "PHYSICAL_LIMITS_UNDEFINED"
    PRESET_POLICY_UNDEFINED = "PRESET_POLICY_UNDEFINED"
    EMERGENCY_PROCEDURE_UNCONFIRMED = "EMERGENCY_PROCEDURE_UNCONFIRMED"
    TELEMETRY_REQUIREMENTS_UNMET = "TELEMETRY_REQUIREMENTS_UNMET"
    OBSERVABILITY_REQUIREMENTS_UNMET = "OBSERVABILITY_REQUIREMENTS_UNMET"
    EQUIPMENT_OWNER_APPROVAL_MISSING = "EQUIPMENT_OWNER_APPROVAL_MISSING"
    HARDWARE_VALIDATION_NOT_COMPLETED = "HARDWARE_VALIDATION_NOT_COMPLETED"


class PhysicalCommandClientKind(StrEnum):
    """Identity of the command client presented as readiness evidence."""

    MISSING = "MISSING"
    FAKE = "FAKE"
    REAL = "REAL"


@dataclass(frozen=True, slots=True)
class PhysicalReadinessEvidence:
    """Explicit evidence supplied by a future reviewed enablement process.

    Defaults intentionally represent the current project state. The fake client
    and test motion profiles do not set the real-client or production-approval
    fields and therefore cannot make physical execution ready.
    """

    command_client_kind: PhysicalCommandClientKind = PhysicalCommandClientKind.MISSING
    production_motion_profile_approved: bool = False
    physical_limits_defined: bool = False
    preset_policy_defined: bool = False
    emergency_procedure_confirmed: bool = False
    telemetry_requirements_met: bool = False
    observability_requirements_met: bool = False
    equipment_owner_approved: bool = False
    hardware_validation_completed: bool = False

    def __post_init__(self) -> None:
        for field in fields(self):
            name = field.name
            value = getattr(self, name)
            if name == "command_client_kind":
                if not isinstance(value, PhysicalCommandClientKind):
                    raise TypeError(f"{name} must be a PhysicalCommandClientKind")
            elif type(value) is not bool:
                raise TypeError(f"{name} must be a bool")


@dataclass(frozen=True, slots=True)
class PhysicalExecutionReadiness:
    """Deterministic readiness result and all blocking reasons."""

    ready: bool
    blocking_reasons: tuple[PhysicalReadinessBlocker, ...]

    def __post_init__(self) -> None:
        if type(self.ready) is not bool:
            raise TypeError("ready must be a bool")
        if self.ready and self.blocking_reasons:
            raise ValueError("a ready result cannot contain blocking reasons")
        if not self.ready and not self.blocking_reasons:
            raise ValueError("a blocked result must contain a blocking reason")

    @property
    def status(self) -> PhysicalReadinessStatus:
        """Return the stable status representation used by callers and logs."""
        return PhysicalReadinessStatus.READY if self.ready else PhysicalReadinessStatus.BLOCKED


class PhysicalExecutionBlockedError(RuntimeError):
    """Raised when a caller attempts physical execution before readiness."""


class PhysicalReadinessEvaluator:
    """Evaluate physical readiness without importing SDKs or touching hardware."""

    def evaluate(
        self,
        *,
        physical_execution_enabled: bool,
        evidence: PhysicalReadinessEvidence | None = None,
    ) -> PhysicalExecutionReadiness:
        """Return readiness from explicit configuration and reviewed evidence."""
        if type(physical_execution_enabled) is not bool:
            raise TypeError("physical_execution_enabled must be a bool")
        evidence = evidence or PhysicalReadinessEvidence()
        blockers: list[PhysicalReadinessBlocker] = []
        if not physical_execution_enabled:
            blockers.append(PhysicalReadinessBlocker.PHYSICAL_EXECUTION_DISABLED)
        if evidence.command_client_kind is not PhysicalCommandClientKind.REAL:
            blockers.append(PhysicalReadinessBlocker.REAL_COMMAND_CLIENT_MISSING)
        if not evidence.production_motion_profile_approved:
            blockers.append(PhysicalReadinessBlocker.PRODUCTION_MOTION_PROFILE_UNAPPROVED)
        if not evidence.physical_limits_defined:
            blockers.append(PhysicalReadinessBlocker.PHYSICAL_LIMITS_UNDEFINED)
        if not evidence.preset_policy_defined:
            blockers.append(PhysicalReadinessBlocker.PRESET_POLICY_UNDEFINED)
        if not evidence.emergency_procedure_confirmed:
            blockers.append(PhysicalReadinessBlocker.EMERGENCY_PROCEDURE_UNCONFIRMED)
        if not evidence.telemetry_requirements_met:
            blockers.append(PhysicalReadinessBlocker.TELEMETRY_REQUIREMENTS_UNMET)
        if not evidence.observability_requirements_met:
            blockers.append(PhysicalReadinessBlocker.OBSERVABILITY_REQUIREMENTS_UNMET)
        if not evidence.equipment_owner_approved:
            blockers.append(PhysicalReadinessBlocker.EQUIPMENT_OWNER_APPROVAL_MISSING)
        if not evidence.hardware_validation_completed:
            blockers.append(PhysicalReadinessBlocker.HARDWARE_VALIDATION_NOT_COMPLETED)
        return PhysicalExecutionReadiness(ready=not blockers, blocking_reasons=tuple(blockers))


class PhysicalExecutionGate:
    """Explicit fail-closed gate for a future physical executor."""

    def __init__(self, evaluator: PhysicalReadinessEvaluator | None = None) -> None:
        self._evaluator = evaluator or PhysicalReadinessEvaluator()

    def evaluate(
        self,
        *,
        physical_execution_enabled: bool,
        evidence: PhysicalReadinessEvidence | None = None,
    ) -> PhysicalExecutionReadiness:
        """Evaluate without opening a connection or initializing a Robot."""
        return self._evaluator.evaluate(
            physical_execution_enabled=physical_execution_enabled,
            evidence=evidence,
        )

    def require_ready(
        self,
        *,
        physical_execution_enabled: bool,
        evidence: PhysicalReadinessEvidence | None = None,
    ) -> PhysicalExecutionReadiness:
        """Reject physical execution unless every gate requirement is satisfied."""
        readiness = self.evaluate(
            physical_execution_enabled=physical_execution_enabled,
            evidence=evidence,
        )
        if not readiness.ready:
            reasons = ", ".join(reason.value for reason in readiness.blocking_reasons)
            raise PhysicalExecutionBlockedError(f"physical execution is blocked: {reasons}")
        return readiness


__all__ = [
    "PhysicalCommandClientKind",
    "PhysicalExecutionBlockedError",
    "PhysicalExecutionGate",
    "PhysicalExecutionReadiness",
    "PhysicalReadinessBlocker",
    "PhysicalReadinessEvidence",
    "PhysicalReadinessEvaluator",
    "PhysicalReadinessStatus",
]
