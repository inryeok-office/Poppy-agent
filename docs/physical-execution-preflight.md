# Physical Execution Software-only Preflight

## Purpose

Issue #77의 preflight는 실제 GO2를 연결하지 않고, 현재 Physical Execution
경로가 안전하게 차단되며 명시적인 test-only evidence를 주입한 경우에만
recording transport까지 흐르는지 검증한다.

이 문서는 physical approval이나 hardware validation을 대체하지 않는다.

## Software-only Boundary

`scripts/physical_execution_preflight.py`는 Server-shaped Command Protocol v1
payload를 parser로 읽고, 기존 safety validator, Physical Execution Gate,
HardwareCommandTarget, UnitreeCommandBackend, `UnitreeSdkCommandClient`를
통과시킨다.

마지막 transport는 `RecordingSportClient` injected double이다. 실제 Unitree
SDK import, DDS initialization, Robot network, SportClient 연결은 수행하지
않는다. `ROBOT_MODE=unitree`, live transport flag, real SDK flag가 지정되면
즉시 실패한다.

## Scenarios

다음 경계를 한 번에 확인한다.

- 기본 evidence와 enable flag만으로는 readiness가 `BLOCKED`이고 factory,
  initialize, dispatch가 모두 0회다.
- test-only synthetic evidence에서 POSTURE `Sit`/`StandUp`이 recording double에
  기록된다.
- `WAIT`, program `STOP`, `PRESET`, profile 없는 `MOVE`/`TURN`은 물리 호출 없이
  처리되거나 실패한다.
- 명시적인 test-only MotionProfile/mapper를 사용할 때만 MOVE/TURN이
  `Move(vx, vy, vyaw)` 형태로 기록된다. 이 숫자는 production motion profile이
  아니다.
- 뒤쪽의 invalid command는 첫 dispatch 전에 전체 preflight에서 거부된다.
- 초기화/operation/shutdown 오류는 fail-closed이며 cleanup 오류가 primary
  execution 결과를 숨기지 않는다.
- cancellation은 `CANCELLED`로 유지되고, 연결 단절은
  `CONNECTED → DEGRADED → CONNECTED` 및 authoritative `FAILED` reconciliation
  fixture로 표현된다. 단절 후 command replay와 duplicate dispatch는 0회다.
- physical execution disabled는 rollback boundary로 유지된다.

## Test-only Synthetic Evidence

`synthetic_test_evidence()`는 harness 내부에만 존재한다. production config,
`main.py`, environment variable 또는 deployment contract에서 이 evidence를
생성할 수 없다. 따라서 이 harness의 recording 성공은 physical readiness를
의미하지 않는다.

## Running

```powershell
python scripts/physical_execution_preflight.py
```

반복 실행해도 외부 자원이나 상태를 만들지 않는다.

## Remaining Physical Blockers

Physical Readiness는 계속 `BLOCKED`다. production motion profile 승인,
physical limits, PRESET policy, emergency procedure, telemetry/observability
hardware evidence, equipment owner approval, hardware validation은 별도
검토가 필요하다.

## Explicit Non-goals

이 preflight는 actual GO2, SportClient, live DDS command publisher, Robot
network, physical movement, physical emergency stop을 사용하거나 검증하지
않는다. 해당 계획과 승인 checklist는 Issue #78의 범위다.
