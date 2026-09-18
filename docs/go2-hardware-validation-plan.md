# Controlled GO2 Hardware Validation Plan

## Purpose

이 문서는 실제 GO2 hardware validation에 들어가기 전에 필요한 승인, 책임,
authoritative constraint, 관찰 항목, 즉시 중단 조건과 evidence 기록 기준을
정의한다. 이 문서는 물리 실행 절차나 movement sequence를 제공하지 않는다.

문서와 checklist의 작성·PR merge는 hardware validation 승인이나 실행 허가가 아니다.
실제 검증은 별도의 승인된 환경과 책임자 확인 없이는 시작하지 않는다.

## Current Readiness Status

```text
BLOCKED
NOT READY FOR PHYSICAL EXECUTION
NOT TESTED ON HARDWARE
```

현재 software boundary와 preflight evidence는 물리 readiness와 분리된다.
`REAL_COMMAND_CLIENT_MISSING`은 software adapter boundary 기준으로 해소됐지만,
owner approval, authoritative physical constraints, emergency responsibility,
hardware telemetry evidence와 hardware validation은 남아 있다.

## Preconditions

다음 조건을 모두 확인하기 전에는 `DO NOT PROCEED`이다.

- equipment owner가 장비 사용을 승인했다.
- supervising operator와 담당 교사 또는 책임 있는 성인이 확인됐다.
- 승인된 validation environment와 참여 범위가 정해졌다.
- 실제 장비·firmware·SDK 정보가 기록되고 authoritative source가 검토됐다.
- 운영 motion profile, physical limits, PRESET policy가 승인됐다.
- physical emergency stop 책임과 실제 장비 절차가 owner/supervisor 및 공식 안내로 확인됐다.
- software preconditions, telemetry criteria, observability criteria가 PASS다.
- [`templates/go2-hardware-validation-record.md`](templates/go2-hardware-validation-record.md)를
  사용할 준비가 됐다.

학생 단독 검증은 허용하지 않는다. 승인되지 않은 사람이 주변에 있는 환경에서
검증하지 않으며, 승인된 공간 밖에서 검증하지 않는다.

## Required Human Approval

문서는 사람의 실제 승인을 대신하지 않는다. 실제 이름을 repository에 추측해
기록하지 않고 역할 또는 승인 reference ID를 사용한다.

- **Equipment owner**: 장비 사용 권한, 장비 상태, operating policy와 physical
  constraints의 승인 책임.
- **Supervising operator**: 검증 현장의 관찰·중단 판단과 승인된 범위 준수 책임.
- **담당 교사 또는 책임 있는 성인**: 학생이 참여하는 경우 감독과 진행 승인 책임.
- **Software operator**: 승인된 software SHA, readiness, observability 및 기록
  상태를 확인하는 책임. 장비 owner나 safety supervisor를 대체하지 않는다.

실제 owner/operator/teacher 승인 reference가 없으면
`EQUIPMENT_OWNER_APPROVAL_MISSING`을 해제하지 않는다.

## Equipment Owner Approval

Equipment owner는 최소한 다음을 authoritative reference와 함께 검토해야 한다.

- 장비 identity/model과 firmware/SDK 정보
- 승인된 command scope와 지원하지 않는 command
- motion profile과 physical limits
- PRESET allow-list 또는 PRESET 금지 결정
- telemetry 및 battery/status 해석
- physical emergency stop 책임과 공식 장비 절차
- 검증 실패 시 disable/rollback 결정권

이 문서는 해당 값을 만들거나 승인하지 않는다. 값이 없으면
`TBD / REQUIRED BEFORE VALIDATION`으로 남긴다.

## Supervising Operator / Teacher

검증에는 supervising operator가 현장에 있어야 하며, 학생이 참여하면 담당 교사
또는 책임 있는 성인이 감독해야 한다. supervisor는 예상하지 않은 상태에서 즉시
검증을 중단할 권한과 책임을 가진다. 책임과 연락/승인 reference가 확인되지 않으면
검증을 시작하지 않는다.

## Authoritative Equipment Information

| Requirement | Required source | Current status | Evidence location |
| --- | --- | --- | --- |
| Motion profile | authoritative product/equipment source + owner approval | `TBD / REQUIRED BEFORE VALIDATION` | validation record |
| Physical limits | authoritative product/equipment source + owner approval | `TBD / REQUIRED BEFORE VALIDATION` | validation record |
| PRESET policy | owner/operator-approved allow-list or explicit prohibition | `TBD / REQUIRED BEFORE VALIDATION` | validation record |
| Emergency responsibility | equipment owner, supervising operator, official guidance | `TBD / REQUIRED BEFORE VALIDATION` | approval reference |
| Telemetry expectations | current Agent boundary + supervised hardware evidence | software boundary exists; hardware evidence missing | validation record |
| Observability expectations | Agent/Server software evidence + supervised validation evidence | software preflight exists; field evidence missing | preflight and validation record |
| Hardware validation result | controlled validation record | `NOT COMPLETED` | validation record |

속도, 거리, 회전각, 가속·감속·제동, 배터리 threshold, obstacle, posture,
torque/joint constraint, emergency response timing은 이 문서에서 결정하지 않는다.

## Validation Scope

검증 범위는 사전에 승인된 software/command/observation 범위로 제한한다. 승인되지
않은 command, PRESET, motion profile 또는 환경을 검증 범위에 포함하지 않는다.
구체적인 movement sequence와 물리 수치는 별도 승인 자료 없이는 작성하지 않는다.

이번 repository에는 다음 software-only evidence가 있다.

- [#76 software command adapter](physical-readiness.md)와 Physical Execution Gate
- [#77 software-only preflight](physical-execution-preflight.md)
- blocked 또는 enable-flag-only 상태에서 factory/init/dispatch 0
- test-only recording transport의 POSTURE 경로
- WAIT physical call 0, program STOP의 physical stop mapping 0
- PRESET 및 profile 없는 MOVE/TURN의 fail-closed
- 명시적 test-only mapping, later-invalid preflight, cancellation
- disconnect/reconciliation, command replay 0, duplicate dispatch 0
- disable/rollback boundary

이 목록은 hardware validation evidence가 아니다.

## Software Preconditions

검증 직전에 다음을 기록·확인한다.

- 승인된 Agent/Server commit SHA
- #75 audit, #76 adapter, #77 preflight의 완료 상태
- `python -m pytest`, `ruff`, `mypy`, harness 및 software-only preflight 결과
- Physical Execution Gate가 존재하고 기본 상태가 blocked인지
- unsupported command와 PRESET이 fail-closed인지
- cancellation, disconnect/reconciliation 및 command replay 방지가 확인됐는지
- disable/rollback 경계가 동작하는지
- physical execution readiness가 `BLOCKED`이면 진행하지 않음

## Telemetry Preconditions

다음 사실이 관찰·기록 가능해야 한다. 숫자 threshold는 authoritative source가
제공하고 owner가 승인하기 전까지 정하지 않는다.

- Robot connection state와 telemetry availability
- Agent connection/operational state
- execution ownership과 lifecycle state
- command result 또는 command failure
- disconnect/recovery/reconciliation 상태
- battery/status 값의 availability와 해석 가능 여부

Telemetry가 사라지거나 의미를 신뢰할 수 없으면 validation을 중단하고
`TELEMETRY_REQUIREMENTS_UNMET`를 유지한다.

## Observability Preconditions

최소한 다음 software 상태가 operator에게 관찰 가능해야 한다.

- Agent startup과 readiness
- execution lifecycle 및 ownership
- dispatch attempt와 failure
- cancellation
- connectivity degradation
- reconciliation/recovery
- shutdown/cleanup
- disable/rollback

raw SDK packet, raw command payload, credential, HTTP auth header 또는 environment
dump를 로그에 요구하지 않는다.

## Stop / Abort Responsibility

다음 개념은 서로 대체하지 않는다.

- **Program STOP**: 현재 program의 이후 command dispatch를 끝내는 software 의미.
- **Execution Cancellation**: execution lifecycle을 취소하는 동작.
- **Administrative Stop**: 승인된 operator/API lifecycle 동작.
- **Physical Emergency Stop**: hardware와 현장 operator의 safety 책임.

Program STOP이나 software cancellation을 physical emergency stop으로 표현하지
않는다. physical emergency stop의 실제 장비 조작 절차는 equipment owner,
supervising operator와 공식 장비 안내가 검증 시작 전에 확인해야 한다.

## Immediate Abort Conditions

다음 중 하나라도 발생하면 validation은 `FAILED`이며 추가 physical execution은
차단한다.

1. 예상하지 않은 motion 또는 command/result mismatch
2. telemetry loss 또는 telemetry 의미 불명확
3. Agent/Server connectivity loss
4. stale execution ownership 또는 Robot ownership 불일치
5. duplicate dispatch 또는 replay 의심
6. cancellation이 무시되거나 잘못 보고됨
7. 승인되지 않은 command/profile/PRESET 실행 시도
8. physical environment가 안전하지 않음
9. supervising operator의 중단 요청
10. equipment owner의 중단 요청

중단 이후에는 원인을 기록하고 owner/operator가 재개를 명시적으로 승인하기
전까지 Physical Readiness를 승격하지 않는다.

검증이 실제로 시작되기 전의 취소나 사전조건 미충족은 `NOT STARTED`로 기록한다.
검증이 시작된 뒤 위 abort condition이 발생하면 `ABORTED`라는 별도 성공/중간
상태를 사용하지 않고 반드시 `FAILED`로 기록한다.

## Rollback / Disable

검증 중 언제든 software physical path를 disable할 수 있어야 한다. disable은
승인된 rollback boundary이며, readiness gate를 우회하는 방법이 아니다.

- disable 상태에서 SDK/client initialization과 dispatch는 발생하지 않아야 한다.
- disable 이후 기존 execution/ownership 상태는 authoritative lifecycle로 기록한다.
- rollback 결과와 남은 상태를 validation record에 남긴다.
- rollback 또는 cleanup이 확인되지 않으면 `DO NOT PROCEED`이다.

## Success Criteria

승인된 범위에서만 다음을 모두 확인하고 evidence를 기록한다.

- reviewed command mapping이 승인된 범위와 일치한다.
- unexpected command, duplicate dispatch, replay가 없다.
- cancellation과 lifecycle status가 실제 결과와 일치한다.
- telemetry와 필수 observability가 유지된다.
- Agent/Server/Robot ownership 상태가 일관된다.
- 실패가 성공으로 보고되지 않는다.
- disable/rollback이 확인된다.
- 모든 승인 reference, 관찰 결과, abort event와 최종 결정이 기록된다.

이 기준은 구체적인 속도·거리·각도·시간을 정하지 않는다.

## Failure Criteria

다음은 validation failure다.

- unexpected physical behavior
- unapproved command 또는 unsupported PRESET
- duplicate/replayed dispatch
- unobservable state 또는 telemetry loss
- incorrect success reporting
- cancellation 무시
- owner/operator stop 요청 무시
- unsafe environment
- disable/rollback 또는 evidence 기록 실패

실패 시 Physical Readiness는 계속 `BLOCKED`이며, 문서/PR 완료를 근거로
재시작하지 않는다.

## Evidence Collection

기록은 [`templates/go2-hardware-validation-record.md`](templates/go2-hardware-validation-record.md)를
복사하여 작성한다. 이름 대신 role/reference ID를 사용할 수 있다. token, raw
header, raw SDK object/payload는 기록하지 않는다.

## Incident Recording

abort, unexpected state, failure, owner/operator decision과 cleanup 결과를
validation record에 연결된 incident reference로 기록한다. 원인과 evidence가
확인되기 전에는 재시도하지 않는다.

## Post-validation Review

검증 종료 후 equipment owner, supervising operator 및 software operator가 결과와
남은 blocker를 검토한다. 성공 기록이 있어도 별도 승인 없이 범위를 넓히지 않는다.
실패 또는 불완전한 evidence는 Physical Readiness를 해제하지 않는다.

## Explicit Non-goals

이 문서는 다음을 수행하거나 정의하지 않는다.

- actual GO2 연결 또는 Robot network 접속
- live SportClient 또는 DDS command publishing
- physical movement 또는 movement sequence
- physical emergency stop 조작 순서
- speed/distance/angle/acceleration/braking/battery/torque 수치
- PRESET 이름, allow-list 또는 mapping
- 실제 hardware validation 실행

## Hardware Safety Boundary

이 plan과 template의 존재, Issue #78의 close, PR merge, software-only preflight
PASS는 hardware approval이나 Physical Readiness `READY`를 의미하지 않는다.

다음 조건이 모두 실제 evidence로 확보되기 전까지는:

```text
DO NOT PROCEED
BLOCKED
NOT READY FOR PHYSICAL EXECUTION
```

- owner/operator/teacher 승인
- authoritative physical constraints
- emergency responsibility
- approved validation environment
- software, telemetry, observability preconditions
- evidence record 준비

## Hardware Readiness Decision Gate

위 조건 중 하나라도 없으면 실제 장비 검증을 시작하지 않는다. 승인과
authoritative information이 확보된 뒤에만 별도 supervised hardware-validation
작업을 계획할 수 있다. 이번 문서는 physical operation sequence를 포함하지 않는다.
