# Software-only Operational Recovery Rehearsal

## Purpose

`scripts/operational_recovery_rehearsal.py`는 지금까지 각각 검증한 Agent 운영 계약을 하나의
persistent local Poppy-Server/PostgreSQL 환경에서 연속적으로 검증한다.

- 정상 Mock Execution
- 실행 중 Server transport outage와 fail-closed reconnect
- interrupted Execution reconciliation
- Agent runtime replacement와 credential fencing
- operational snapshot
- Robot fixture lifecycle과 최종 ownership 정리

이 rehearsal은 새로운 production lifecycle이나 ownership 정책을 추가하지 않는다. Server DB가
Execution lifecycle의 authoritative source이며, Agent local memory는 복구의 source of truth가
아니다.

## Safety Boundary

모든 실행은 localhost HTTP, PostgreSQL, Mock Agent/Robot만 사용한다. Unitree SDK, SportClient,
DDS command publisher, 실제 GO2, physical movement, physical emergency stop은 사용하지 않는다.
Rehearsal PASS는 Physical Readiness를 의미하지 않으며, Physical Readiness는 계속 `BLOCKED`다.

Command replay, 마지막 command 추측, 남은 거리·각도·WAIT 시간 추측은 수행하지 않는다. 진행률을
알 수 없는 interrupted Execution은 기존 recovery contract에 따라 reconciliation한다.

## Preconditions

문서화된 ephemeral local Poppy-Server/PostgreSQL 환경을 실행하고 bootstrap Agent token을
환경 변수로 제공한다.

```powershell
$env:POPPY_E2E_SERVER_URL = "http://localhost:8080"
$env:POPPY_E2E_AGENT_TOKEN = "<local-test-bootstrap-token>"
python scripts/operational_recovery_rehearsal.py
```

실제 token 값은 shell history, 로그, snapshot, PR body에 기록하지 않는다.

## Scenario Timeline

한 번의 rehearsal run은 하나의 Robot fixture와 persistent Server DB를 공유한다.

1. clean startup, registration, recovery 완료, `READY/CONNECTED`
2. 정상 Execution의 `QUEUED → ASSIGNED → RUNNING → COMPLETED`
3. 두 번째 active Execution을 `RUNNING`까지 진행
4. controllable ServerClient transport outage 주입
5. `DEGRADED`, 새 polling 차단, cooperative interruption 확인
6. transport 복구와 Server authoritative reconciliation 확인
7. 세 번째 Execution 중 Agent runtime replacement와 credential rotation 확인
8. OLD credential fencing과 stale terminal report 보호 확인
9. replacement Agent로 새 Execution 완료
10. snapshot, Execution, Robot ownership의 최종 일관성 audit

## Failure Injection

Harness의 `FaultInjectingServerClient`는 production client에 test flag를 넣지 않고 테스트
경계에서 transport 메서드 호출을 deterministic하게 실패시킨다. HTTP가 다시 가능해지면
동일한 real client 경로로 Server와 통신한다.

실행 중 outage에서는 User Cancellation을 발생시키지 않는다. Agent는 connectivity를
`DEGRADED`로 표시하고 cooperative interruption 및 기존 reconciliation contract를 사용한다.

## Recovery and Fencing

Agent replacement는 같은 logical Agent/Robot으로 등록한다. Server의 기존 credential rotation을
사용하여 NEW credential만 유효하게 하고 OLD credential의 heartbeat, polling, status 조회·보고,
recovery 요청을 거부한다. 이전 Execution은 처음부터 다시 실행하지 않으며 command replay count는
0이어야 한다.

## Operational Snapshot Expectations

주요 상태는 local atomic JSON snapshot에서 확인한다.

- clean/recovered idle: `READY`, `CONNECTED`, `operationalReady=true`, `acceptingNewExecution=true`
- active Execution: `activeExecutionId`가 존재하고 새 Execution 수락 불가
- outage: `DEGRADED`, `operationalReady=false`, `acceptingNewExecution=false`
- recovered idle: 다시 `READY/CONNECTED` 및 새 Execution 수락 가능

Snapshot에는 credential, Authorization/header, command payload, session token 또는 raw response를
포함하지 않는다.

## Cleanup

성공·실패 모두 `finally`에서 runtime thread를 cooperative하게 종료하고, 기존 공식 admin
Robot lifecycle API로 fixture를 `UNAVAILABLE` 처리한다. DB 직접 UPDATE/DELETE, heartbeat timeout을
기다리는 sleep, hidden test-only Server endpoint는 사용하지 않는다. cleanup은 bounded하며,
실패는 rehearsal 결과를 숨기지 않고 non-zero로 보고한다.

같은 persistent local environment에서 연속 실행할 때도 이전 Robot이 다음 allocation에 참여하지
않도록 공식 fixture retirement를 사용한다.

## Automated vs Manual Checks

Agent runtime replacement와 transport outage는 deterministic하게 자동 검증한다. Docker 전체나
host network interface를 조작하지 않으므로 Poppy-Server application process 자체의 restart와
실제 systemd/boot recovery는 이 harness의 자동 범위가 아니다. 필요한 경우 PostgreSQL 데이터를
유지한 Server process restart를 별도 수동 rehearsal 항목으로 검증한다.

## Operator Checklist (software state only)

- local status snapshot이 존재하고 JSON으로 읽힌다.
- connectivity가 `CONNECTED`이며 operational readiness가 정상이다.
- stale active Execution과 Robot ownership이 없다.
- OLD credential 요청이 허용되지 않고 NEW credential만 유효하다.
- 최종 Execution과 Robot release 상태가 Server API에서 일치한다.

## Explicit Non-goals

이 문서는 GO2 조작, physical test procedure, production motion profile, hardware safety limit,
PRESET policy, emergency stop 구현 또는 실제 physical execution enablement를 정의하지 않는다.
