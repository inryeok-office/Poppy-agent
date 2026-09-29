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

실제 장비 검증에 진입하기 위한 승인 역할, authoritative 제약 source, 관찰 항목,
즉시 중단 조건과 evidence 기록 형식은
[`go2-hardware-validation-plan.md`](go2-hardware-validation-plan.md)와
[`templates/go2-hardware-validation-record.md`](templates/go2-hardware-validation-record.md)에
정의한다. 이 계획서와 template의 작성·merge는 승인 완료나 hardware validation 완료를
뜻하지 않는다.

The current Agent contains an optional, lazy real Unitree command adapter, but
`ROBOT_MODE=unitree` remains registration/telemetry-only unless the readiness
gate is explicitly satisfied. The adapter is not initialized in the current
blocked configuration. The Fake Unitree client and test motion profiles are
test doubles, not physical-readiness evidence.

## Current Repository and Runtime Evidence

이 문서에 기록한 SHA는 2026-09-29 evidence collection snapshot이다. PR 병합이나 후속 커밋으로 develop이 이동하면 이 값은 current develop을 뜻하지 않는다. 실제 hardware validation 직전에는 latest Agent와 Server develop SHA를 다시 조회해 validation record에 기록해야 한다.

- Poppy-agent `develop` at evidence collection: `c1bdbe5c82fa245916e4519225023fb89279dc63`
- Poppy-Server `develop` at evidence collection: `3951e51dfe453dc215d6eeb190997235b3aeaabb`

실제 Ubuntu deployment에서 확인된 Agent는 다음과 같다.

- deployed Agent: `d6fc2f1acab258c200583f1fc946a44eea29fb42`
- drift measured against the evidence collection Agent `develop` snapshot: 53 commits behind, 0 commits ahead
- classification: `STALE / NOT REPRESENTATIVE OF CURRENT_DEVELOP`
- current hardware validation 사용 적격성: `NOT ELIGIBLE FOR CURRENT HARDWARE VALIDATION`

evidence collection 당시 deployed SHA에는 그 시점 Agent develop의 다음 physical-safety boundary가 없었다.

- `PhysicalExecutionGate`
- `UnitreeSdkCommandClient`
- physical execution software-only preflight
- controlled GO2 hardware validation plan
- PRESET fail-closed boundary
- current MOVE/TURN mapper boundary
- physical execution default-disabled gate

이 deployment drift는 이번 문서 갱신에서 기록만 하며, deployment update나 service
변경을 수행하지 않는다.

### Runtime SDK Evidence

실제 systemd runtime Python에서 확인한 SDK evidence는 다음과 같다.

- distribution: `unitree_sdk2py 1.0.1`
- checkout: `/home/poppy/poppy/unitree_sdk2_python`
- remote: `https://github.com/unitreerobotics/unitree_sdk2_python.git`
- base commit: `65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5`
- checkout describe: `65691c8-dirty`
- editable install: `YES`
- runtime linkage: `CONFIRMED_RUNTIME_SDK`
- checkout state: `DIRTY`
- dirty file: `unitree_sdk2py/test/lowlevel/read_lowstate.py`
- dirty change: telemetry helper의 NIC 이름 `enp2s0` → `enp3s0`
- dirty scope: 총 2줄 변경, SDK production runtime library 변경 없음
- runtime import path 영향: `NO`
- dirty patch SHA256: `087ffbeb362f8453397484d0205c1bf8719c7322ad94a6e9992a19ae80f4205d`
- exact runtime evidence: `PROVIDED_WITH_DIRTY_NON_RUNTIME_HELPER`

CycloneDDS는 Unitree SDK version과 별도의 runtime distribution이며, 확인된 version은
`0.10.2`다.

### Device and Configuration Evidence

사용자가 제공한 실제 device evidence는 다음과 같이 기록한다.

- model/edition: `Unitree GO2 EDU`
- Robot Software Version: `V1.0.24`
- Hardware Version: `V1.0`
- SN: device에서 확인됨; 전체값은 기록하지 않음 (`PROVIDED / REDACTED`)
- Firmware exact version: `MISSING`

`V1.0.24`는 device 화면의 `Software Version` label을 보존한 값이다. 이를
`Firmware Version`으로 재명명하지 않는다.

`/etc/poppy-agent/poppy-agent.env`는 존재하며 `root:root`, mode `600`이지만, 이번
evidence run에서는 내용에 접근할 수 없었다. 따라서 실제 `ROBOT_MODE`, Robot UUID,
model/edition, firmware, SDK metadata, `POPPY_ENABLE_PHYSICAL_EXECUTION` 값은
`UNAVAILABLE`로 유지하며 repository의 example 값을 runtime 값으로 사용하지 않는다.

## Readiness architecture

```text
AgentConfig.POPPY_ENABLE_PHYSICAL_EXECUTION
    + reviewed PhysicalReadinessEvidence
    -> PhysicalReadinessEvaluator
    -> PhysicalExecutionReadiness
    -> PhysicalExecutionGate
    -> gated Unitree command adapter (disabled)
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

The current production runtime still creates an executor only for `mock` mode.
If physical execution is requested in Unitree mode while readiness is blocked,
startup fails before the SDK client factory or backend initialization is called.
No force, unsafe, skip-safety, or development bypass is provided.

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
    -> reviewed real command client adapter (optional, gate required)
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

This contract does not perform:

- GO2 connection or movement
- live Unitree `SportClient` calls
- DDS command publishing
- physical emergency stop
- hardware tests
- production safety values
- PRESET mapping

Hardware validation status: **NOT TESTED ON HARDWARE**.
현재 validation baseline은 위 snapshot에서 자동으로 파생되지 않는다. 검증 실행 시점의 current SHA와 실제 deployed SHA를 별도로 확인한다.
