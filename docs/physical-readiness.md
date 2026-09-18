# Physical Readiness Contract

## Scope

This contract defines the conditions that must be satisfied before Poppy may
enable physical Robot command execution. It does not describe how to operate a
Robot and does not authorize hardware use.

## Current Status

```text
BLOCKED
NOT READY FOR PHYSICAL EXECUTION
Hardware validation status: NOT TESTED ON HARDWARE
```

현재 blocker의 상태·evidence·remaining gap은
[`pre-hardware-gap-audit.md`](pre-hardware-gap-audit.md)에 기록한다. 이 감사 문서의
software evidence는 physical execution 승인이나 hardware validation 완료를 의미하지
않으며, 모든 물리 실행 전제 조건은 계속 fail-closed로 평가된다.

The current Agent has no real Unitree command client and `ROBOT_MODE=unitree`
remains registration/telemetry-only. The Fake Unitree client and test motion
profiles are test doubles, not physical-readiness evidence.

## Readiness architecture

```text
AgentConfig.POPPY_ENABLE_PHYSICAL_EXECUTION
    + reviewed PhysicalReadinessEvidence
    -> PhysicalReadinessEvaluator
    -> PhysicalExecutionReadiness
    -> PhysicalExecutionGate
    -> future physical executor (disabled)
```

`PhysicalExecutionReadiness` is deterministic and contains `ready` plus an
ordered tuple of `blocking_reasons`. The gate is fail-closed: an attempt to use a
blocked result raises `PhysicalExecutionBlockedError`.

The current evaluator requires all of the following evidence:

- a real command client is available (the fake client is not sufficient)
- a production motion profile is approved
- physical motion limits are defined
- PRESET policy and mapping are defined
- emergency/stop procedure is confirmed by the responsible people
- telemetry requirements are met
- command and lifecycle observability requirements are met
- equipment-owner approval exists
- hardware validation is completed

## Software enablement gate

`POPPY_ENABLE_PHYSICAL_EXECUTION` defaults to `false` and accepts only `true` or
`false`. The flag is an enablement request, not an approval. Physical execution
would require both the flag and a fully ready evaluation:

```text
physical_execution_enabled == true AND readiness.ready == true
```

The current production runtime still creates an executor only for `mock` mode;
Unitree mode does not obtain a command executor. No force, unsafe, skip-safety,
or development bypass is provided.

## Motion safety requirements

The following must be decided from authoritative product and equipment sources
before physical enablement:

- maximum linear/angular speed
- maximum MOVE distance and TURN angle
- acceleration, deceleration, and braking behavior
- battery, obstacle, posture, joint, torque, and emergency-latency policy

All of these values are currently **TBD**. SDK technical capabilities are not
Poppy operating limits.

An injected test `MotionProfile` only supports deterministic planning tests. It
does not constitute an approved production profile.

## Command mapping requirements

The existing boundary remains:

```text
typed program
    -> safety validator
    -> hardware-neutral intent
    -> motion strategy / command backend
    -> reviewed real command client (future)
```

The real client must be separately reviewed and must preserve Poppy command
semantics. Distance-to-velocity and angle-to-yaw-rate conversions must not be
invented in the readiness layer.

## PRESET policy

Physical PRESET execution is blocked until an explicit allow-list, mapping, and
unsupported-preset behavior are approved. No preset names or mappings are
defined here. Fake trace support does not satisfy this requirement.

## Stop responsibility boundaries

- **Program STOP** ends dispatch of later commands in the current program.
- **Execution Cancellation** is a lifecycle operation, separate from STOP.
- **Administrative Stop** is a future operator/API lifecycle operation.
- **Physical Emergency Stop** is a hardware/operator safety responsibility.

The physical emergency stop is not implemented, simulated, or mapped to a
Unitree command in this phase.

## Runtime failure requirements

Agent crash, Server or Robot connection loss, status-report failure, backend
exception, and unavailable targets must never be interpreted as successful
completion. The execution result and lifecycle reporting must remain fail-closed.
Recovery behavior requires a separate reviewed contract; this document does not
invent hardware recovery actions.

## Telemetry and observability requirements

Before enablement, the system must make at least these facts observable:

- Robot connection and operational state
- current execution ownership
- command dispatch and failure result
- execution lifecycle state
- Agent health and connectivity
- mechanism to disable or roll back the physical path

No sensor threshold or hardware control procedure is defined here.

## Equipment owner and operator approval

Physical limits, stop responsibilities, operating policy, and validation evidence
must be reviewed and approved by the responsible equipment owner and supervising
operator/teacher where applicable. This PR does not create operating instructions
or replace that approval.

## Hardware validation requirement

Hardware validation remains an unresolved prerequisite. A future controlled test
plan must review mapping, telemetry, failure reporting, ownership, operator-visible
status, and the disable/rollback mechanism. This document intentionally contains
no physical setup or movement sequence.

## Current blocking reasons

The evaluator uses these stable reasons:

- `PHYSICAL_EXECUTION_DISABLED`
- `REAL_COMMAND_CLIENT_MISSING`
- `PRODUCTION_MOTION_PROFILE_UNAPPROVED`
- `PHYSICAL_LIMITS_UNDEFINED`
- `PRESET_POLICY_UNDEFINED`
- `EMERGENCY_PROCEDURE_UNCONFIRMED`
- `TELEMETRY_REQUIREMENTS_UNMET`
- `OBSERVABILITY_REQUIREMENTS_UNMET`
- `EQUIPMENT_OWNER_APPROVAL_MISSING`
- `HARDWARE_VALIDATION_NOT_COMPLETED`

Unknown or unresolved requirements must add a blocker rather than permit
execution.

## Explicit non-goals

This contract does not implement or perform:

- GO2 connection or movement
- Unitree `SportClient` calls
- DDS command publishing
- physical emergency stop
- hardware tests
- production safety values
- PRESET mapping

Hardware validation status: **NOT TESTED ON HARDWARE**.
