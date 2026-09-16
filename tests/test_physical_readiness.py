import pytest

from poppy_agent.execution import (
    PhysicalCommandClientKind,
    PhysicalExecutionBlockedError,
    PhysicalExecutionGate,
    PhysicalReadinessBlocker,
    PhysicalReadinessEvaluator,
    PhysicalReadinessEvidence,
    PhysicalReadinessStatus,
)
from poppy_agent.hardware import FakeUnitreeCommandClient


def test_default_readiness_is_blocked_with_deterministic_reasons() -> None:
    readiness = PhysicalReadinessEvaluator().evaluate(physical_execution_enabled=False)

    assert readiness.ready is False
    assert readiness.status is PhysicalReadinessStatus.BLOCKED
    assert readiness.blocking_reasons == (
        PhysicalReadinessBlocker.PHYSICAL_EXECUTION_DISABLED,
        PhysicalReadinessBlocker.REAL_COMMAND_CLIENT_MISSING,
        PhysicalReadinessBlocker.PRODUCTION_MOTION_PROFILE_UNAPPROVED,
        PhysicalReadinessBlocker.PHYSICAL_LIMITS_UNDEFINED,
        PhysicalReadinessBlocker.PRESET_POLICY_UNDEFINED,
        PhysicalReadinessBlocker.EMERGENCY_PROCEDURE_UNCONFIRMED,
        PhysicalReadinessBlocker.TELEMETRY_REQUIREMENTS_UNMET,
        PhysicalReadinessBlocker.OBSERVABILITY_REQUIREMENTS_UNMET,
        PhysicalReadinessBlocker.EQUIPMENT_OWNER_APPROVAL_MISSING,
        PhysicalReadinessBlocker.HARDWARE_VALIDATION_NOT_COMPLETED,
    )


def test_enable_flag_does_not_override_unresolved_requirements() -> None:
    readiness = PhysicalReadinessEvaluator().evaluate(physical_execution_enabled=True)

    assert readiness.ready is False
    assert PhysicalReadinessBlocker.PHYSICAL_EXECUTION_DISABLED not in readiness.blocking_reasons
    assert PhysicalReadinessBlocker.REAL_COMMAND_CLIENT_MISSING in readiness.blocking_reasons


def test_fake_client_is_not_real_client_readiness_evidence() -> None:
    _fake_client = FakeUnitreeCommandClient()
    readiness = PhysicalReadinessEvaluator().evaluate(
        physical_execution_enabled=True,
        evidence=PhysicalReadinessEvidence(
            command_client_kind=PhysicalCommandClientKind.FAKE,
        ),
    )

    assert readiness.ready is False
    assert PhysicalReadinessBlocker.REAL_COMMAND_CLIENT_MISSING in readiness.blocking_reasons


def test_test_profile_is_not_production_profile_approval() -> None:
    readiness = PhysicalReadinessEvaluator().evaluate(
        physical_execution_enabled=True,
        evidence=PhysicalReadinessEvidence(
            command_client_kind=PhysicalCommandClientKind.REAL,
        ),
    )

    assert readiness.ready is False
    assert (
        PhysicalReadinessBlocker.PRODUCTION_MOTION_PROFILE_UNAPPROVED in readiness.blocking_reasons
    )


def test_gate_rejects_even_when_enable_flag_is_true() -> None:
    gate = PhysicalExecutionGate()

    with pytest.raises(PhysicalExecutionBlockedError, match="physical execution is blocked"):
        gate.require_ready(physical_execution_enabled=True)


def test_complete_synthetic_evidence_can_be_evaluated_without_sdk_or_robot() -> None:
    evidence = PhysicalReadinessEvidence(
        command_client_kind=PhysicalCommandClientKind.REAL,
        production_motion_profile_approved=True,
        physical_limits_defined=True,
        preset_policy_defined=True,
        emergency_procedure_confirmed=True,
        telemetry_requirements_met=True,
        observability_requirements_met=True,
        equipment_owner_approved=True,
        hardware_validation_completed=True,
    )

    readiness = PhysicalExecutionGate().evaluate(
        physical_execution_enabled=True,
        evidence=evidence,
    )

    assert readiness.ready is True
    assert readiness.status is PhysicalReadinessStatus.READY
    assert readiness.blocking_reasons == ()


@pytest.mark.parametrize("value", [None, 1, "true"])
def test_readiness_evidence_rejects_non_boolean_requirements(value: object) -> None:
    with pytest.raises(TypeError, match="production_motion_profile_approved"):
        PhysicalReadinessEvidence(production_motion_profile_approved=value)  # type: ignore[arg-type]


def test_readiness_evaluator_rejects_non_boolean_enable_flag() -> None:
    with pytest.raises(TypeError, match="physical_execution_enabled"):
        PhysicalReadinessEvaluator().evaluate(physical_execution_enabled="true")  # type: ignore[arg-type]
