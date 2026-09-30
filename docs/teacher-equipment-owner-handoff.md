# Teacher / Equipment Owner Project Handoff

이 문서는 Poppy 프로젝트와 Unitree GO2 EDU를 인수인계받은 교사·장비 담당자가
현재 software 상태를 이해하고, 실제 hardware validation 전에 승인해야 할 항목을
확인하기 위한 handoff다. 이 문서는 Robot 운용 절차나 movement sequence를
정의하지 않는다.

Audit date: `2026-09-30` (Asia/Seoul)

## Current Baseline

| Item | Value |
| --- | --- |
| Poppy-agent latest develop | `8a75d0635f035f6eb47969d3196c4dc8c2f28ada` |
| Poppy-Server latest develop | `3951e51dfe453dc215d6eeb190997235b3aeaabb` |
| Actual deployed Agent | `d6fc2f1acab258c200583f1fc946a44eea29fb42` |
| Deployment drift | 57 commits behind, 0 commits ahead |
| Runtime Python | `3.11.0rc1` at `/home/poppy/projects/Poppy-agent/.venv/bin/python` |
| Unitree runtime SDK | `unitree_sdk2py 1.0.1` |
| SDK base commit | `65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5` |
| CycloneDDS | `0.10.2` |
| Robot | Unitree GO2 EDU |
| Robot Software Version | `V1.0.24` |
| Hardware Version | `V1.0` |
| Firmware exact | `MISSING` |
| Physical Readiness | `BLOCKED` |

실제 deployed Agent는 current develop의 physical-readiness safety boundary를
포함하지 않으므로 current hardware validation software baseline으로 사용하지
않는다. #89 controlled deployment approval은 `PROVIDED`지만 deployment execution은
`NOT_STARTED`다.

## Teacher Architecture Brief

### Poppy의 역할

Poppy는 학생이 만든 block program을 session과 revision으로 관리하고, simulation
pass와 실행 요청을 연결한 뒤, 승인된 Robot에 execution을 전달하는 서비스다.
Poppy-Server는 Web client와 Python Agent 사이의 계약을 관리한다. Poppy-Client는
이번 handoff 범위에 포함하지 않는다.

Server의 simulation pass는 실행을 허용하기 위한 software 상태와 revision 확인이다.
그 상태만으로 GO2가 움직였거나 hardware validation이 끝났다는 뜻은 아니다.

### Server 역할

Poppy-Server의 주요 책임은 다음과 같다.

- session, block revision, mission과 simulation pass 보관
- execution 요청을 검증하고 `QUEUED` 상태로 관리
- Robot capability와 Agent binding을 확인해 execution을 배정
- Agent 등록, heartbeat, execution polling/status/recovery API 제공
- cancellation, ownership, duplicate allocation과 lifecycle 상태 관리

최신 Server develop은 `3951e51d...`이며 Agent 내부 API는 `X-Agent-Token` 인증과
Agent registration/heartbeat/execution contract를 사용한다. 실제 deployed Server
SHA는 현재 확인되지 않았다.

### Agent 역할

Poppy-agent는 Python runtime boundary다.

1. `AgentConfig`와 `ServerConfig`가 environment를 검증한다.
2. `Agent`가 Mock 또는 Unitree telemetry adapter를 선택하고 시작한다.
3. `AgentServerRuntime.start()`가 Robot adapter를 시작하고 Server에 Agent를 등록한다.
4. heartbeat가 Robot 상태와 Agent 상태를 Server에 전달한다.
5. `fetch_next_execution()`으로 배정된 execution을 polling한다.
6. `HighLevelCommandProtocolParser`가 JSON command program을 typed model로 파싱한다.
7. `ExecutionSafetyValidator`가 protocol, Robot identity, sequence, parameter,
   target support와 command preflight를 검사한다.
8. executor가 Mock trace 또는 승인된 hardware boundary로 execution lifecycle을
   처리한다.
9. 결과를 `COMPLETED`, `FAILED`, `CANCELLED` 중 하나로 Server에 보고한다.

### 실제 GO2와 연결되는 지점

현재 코드에는 두 개의 서로 다른 Unitree 경계가 있다.

- `src/poppy_agent/robot/unitree.py`의 `UnitreeGo2Adapter`는 `rt/lowstate`를 읽는
  telemetry adapter다. `ROBOT_MODE=unitree`로 Agent를 실제 시작하면 이 adapter가
  DDS channel과 read-only subscriber를 초기화할 수 있다. 이 경계는 command client가
  아니며 Robot command를 발행하지 않는다.
- `src/poppy_agent/hardware/unitree_sdk.py`의 `UnitreeSdkCommandClient`는 future
  physical command adapter다. 이 client가 official `SportClient`와
  `ChannelFactoryInitialize`에 도달하는 것은 `PhysicalExecutionGate`를 통과한
  별도의 physical execution 경로에서만 가능하다.

physical command 흐름은 다음과 같이 gate 뒤에 있다.

```text
Server execution
  -> Agent polling
  -> command parser
  -> ExecutionSafetyValidator
  -> PhysicalExecutionGate
  -> HardwareCommandTarget
  -> UnitreeCommandBackend
  -> explicit MotionExecutionStrategy / mapper
  -> UnitreeSdkCommandClient
  -> official Unitree SportClient
```

현재 readiness evidence가 완성되지 않았고 `POPPY_ENABLE_PHYSICAL_EXECUTION`의
기본값도 `false`이므로 gate는 fail-closed 상태다. `true`라는 flag 하나만으로
실행이 허용되지 않는다.

### 현재 실제 physical path가 막혀 있는 이유

현재 code와 evidence가 요구하는 조건 중 다음이 남아 있다.

- approved production motion profile
- approved physical limits
- PRESET allow-list 또는 명시적 exclusion policy
- complete physical emergency responsibility/procedure
- field telemetry와 observability evidence
- hardware validation result
- current safety boundary를 포함한 Agent deployment
- authoritative firmware exact evidence

Mock client, synthetic readiness evidence, test-only motion profile과 software-only
preflight는 이 조건을 대신하지 않는다.

### 문제 발생 시 어디를 확인해야 하는지

문제의 종류에 따라 다음 순서로 확인한다.

| 증상 | 우선 확인 위치 | 의미 |
| --- | --- | --- |
| Agent가 등록되지 않음 | `docs/configuration.md`, systemd `ExecStart`, EnvironmentFile key 존재 여부 | 설정·경로·인증 contract 문제 가능성 |
| heartbeat가 끊김 | `AgentServerRuntime`, operational status, Server Agent/Robot contract | Server connectivity 또는 lifecycle 문제 |
| execution이 배정되지 않음 | Server allocation/binding/capability 상태 | Robot identity와 capability contract 확인 필요 |
| command가 거부됨 | `HighLevelCommandProtocolParser`, `ExecutionSafetyValidator`, readiness blocker | malformed 또는 승인되지 않은 command |
| physical path가 시작되지 않음 | `PhysicalExecutionGate`와 readiness evidence | fail-closed safety 동작일 수 있음 |
| 중단/취소가 혼동됨 | cancellation lifecycle과 Program STOP 의미 | Physical Emergency Stop과 별개 |
| 현재 배포와 문서가 다름 | deployed SHA, target develop SHA, #89 | stale deployment 여부 확인 |

로그를 확인할 때 token, UUID 전체값, SN, raw SDK payload는 기록하거나 공유하지
않는다.

## Simulation, Mock, Physical의 차이

| 구분 | 실제 의미 | Robot 접근 |
| --- | --- | --- |
| Simulation pass | Server가 특정 revision을 software 상태로 검증했다는 기록 | 없음 |
| Mock execution | typed command를 in-memory trace로 기록하는 개발 실행 | 없음 |
| Read-only Unitree telemetry | `rt/lowstate`를 읽어 identity/status를 관찰하는 adapter | DDS subscriber 가능; command 없음 |
| Physical execution | readiness gate 뒤의 real command adapter 경로 | 현재 승인·배포·hardware evidence 부족으로 차단 |

### STOP, cancellation, physical emergency stop

- **Program STOP**은 현재 program의 이후 command dispatch를 끝내는 software
  의미다. Unitree `StopMove` 호출과 동일하지 않다.
- **Execution cancellation**은 Server와 Agent execution lifecycle을
  `CANCELLED`로 정리하는 software 동작이다.
- **Physical Emergency Stop**은 장비와 현장 operator가 책임지는 hardware
  safety procedure다. 현재 repository는 이를 구현하거나 대신하지 않는다.

## Physical Readiness Recheck

| Blocker | Status | Evidence |
| --- | --- | --- |
| `PHYSICAL_EXECUTION_DISABLED` | `RESOLVED` (의도된 safety default) | `AgentConfig` 기본값 false, `tests/test_physical_readiness.py` |
| `REAL_COMMAND_CLIENT_MISSING` | `RESOLVED` (software boundary) | `UnitreeSdkCommandClient`, `tests/test_unitree_sdk.py` |
| `PRODUCTION_MOTION_PROFILE_UNAPPROVED` | `BLOCKED` | `PhysicalReadinessEvaluator`, `docs/physical-readiness.md`, #83 |
| `PHYSICAL_LIMITS_UNDEFINED` | `BLOCKED` | readiness evaluator와 hardware plan의 TBD 상태 |
| `PRESET_POLICY_UNDEFINED` | `BLOCKED` | PRESET fail-closed test/preflight, 승인 allow-list 없음 |
| `EMERGENCY_PROCEDURE_UNCONFIRMED` | `PARTIAL` | 안전 우선·이상 시 중단 확인; 책임/재시작/복구 절차 미정 |
| `TELEMETRY_REQUIREMENTS_UNMET` | `PARTIAL` | read-only adapter와 software contract 존재; field evidence 없음 |
| `OBSERVABILITY_REQUIREMENTS_UNMET` | `PARTIAL` | structured status/logging 존재; 현장 관찰 증거 없음 |
| `EQUIPMENT_OWNER_APPROVAL_MISSING` | `RESOLVED` (일반 사용 승인) | #83 human approval evidence; 구체적 physical scope는 별도 |
| `HARDWARE_VALIDATION_NOT_COMPLETED` | `BLOCKED` | 실제 hardware validation 미실시 |

이 표에서 `RESOLVED`는 해당 software 또는 일반 승인 항목이 확인됐다는 뜻이며,
전체 Physical Readiness가 READY가 됐다는 뜻이 아니다.

## Human Approval Evidence

- equipment/institution approval: `PROVIDED`
- responsible teacher: `PROVIDED` (role-only)
- supervising adult/operator: `PROVIDED` (role-only)
- approved environment: `PROVIDED` — AI자율주행실습실
- general development validation authorization: `PROVIDED`
- bounded physical movement scope: `PARTIAL`
- approved physical limits: `MISSING`
- production motion profile: `MISSING`
- emergency procedure: `PARTIAL`
- firmware exact: `MISSING`
- controlled deployment approval: `PROVIDED`

`V1.0.24`는 Robot Software Version이며 firmware exact evidence가 아니다.

## Decisions Required from the Teacher / Equipment Owner

### Decision 1 — Bounded movement scope

- **Why required:** general development approval만으로는 어떤 physical command를
  허용했는지 알 수 없다.
- **Current state:** `PARTIAL`; 구체적인 MOVE/TURN 또는 posture 범위 미정.
- **Code/doc:** `PhysicalReadinessEvidence`, `go2-hardware-validation-plan.md`.
- **What to decide:** 허용할 command category와 명시적으로 제외할 category.
- **Evidence:** role-only approval reference와 승인된 scope 문서.

### Decision 2 — Production motion profile

- **Why required:** Poppy의 distance/angle semantics를 Unitree의 velocity-shaped
  operation으로 변환하는 기준이 필요하다.
- **Current state:** `MISSING`; test-only profile은 production approval이 아니다.
- **Code/doc:** `MotionExecutionStrategy`, `UnitreeMotionMapper`, readiness evaluator.
- **What to decide:** 승인된 profile과 완료 조건.
- **Evidence:** authoritative source와 owner approval reference.

### Decision 3 — Physical limits

- **Why required:** SDK가 허용하는 최대값은 학교의 운용 한도가 아니다.
- **Current state:** `MISSING`.
- **Code/doc:** `PhysicalReadinessEvidence.physical_limits_defined`, hardware plan.
- **What to decide:** 승인된 속도·거리·각도·가감속·제동·배터리·장애물·자세·토크·응답 기준.
- **Evidence:** 수치의 authoritative source와 승인 reference.

### Decision 4 — PRESET policy

- **Why required:** 이름만으로 preset의 실제 동작과 위험을 알 수 없다.
- **Current state:** `MISSING`; physical PRESET은 fail-closed.
- **Code/doc:** `ExecutionSafetyValidator`, `UnitreeCommandBackend`, preflight.
- **What to decide:** allow-list, mapping, 또는 physical PRESET 금지.
- **Evidence:** 승인된 policy와 제외 목록.

### Decision 5 — Emergency responsibility

- **Why required:** Program STOP이나 software cancellation은 hardware emergency stop이
  아니다.
- **Current state:** `PARTIAL`; 안전 우선과 이상 시 중단 방향만 확인됐다.
- **Code/doc:** physical readiness plan의 stop responsibility와 abort conditions.
- **What to decide:** 누가 중단을 선언하는지, restart 조건과 recovery 책임.
- **Evidence:** formal operator responsibility와 authoritative equipment procedure.

### Decision 6 — Field telemetry and success criteria

- **Why required:** software PASS만으로 hardware가 정상이라고 판단할 수 없다.
- **Current state:** `PARTIAL`; software observability는 있으나 field evidence 없음.
- **Code/doc:** telemetry/observability requirements와 validation record template.
- **What to decide:** 검증 중 관찰할 상태, 성공/실패 판정, 기록 방식.
- **Evidence:** validation record의 timestamp, SHA, observed state, incident/abort reference.

## Teacher Validation Checklist

### 내가 코드 쪽에서 확인할 것

- [ ] validation 직전 latest Agent/Server SHA를 확인한다.
- [ ] deployed Agent가 target safety baseline과 일치하는지 확인한다.
- [ ] `PhysicalExecutionGate`와 default-disabled 정책을 확인한다.
- [ ] software-only preflight와 전체 Agent test 결과를 확인한다.
- [ ] Mock trace와 real hardware evidence를 서로 바꾸어 기록하지 않는다.

### 내가 배포 전에 승인할 것

- [ ] target SHA와 rollback SHA를 문서에 기록한다.
- [ ] EnvironmentFile의 key 존재 여부를 secret-safe 방식으로 확인한다.
- [ ] token, UUID, SN, private network 값이 문서·로그에 나오지 않는지 확인한다.
- [ ] Python, SDK, CycloneDDS compatibility와 systemd runtime path를 확인한다.
- [ ] 배포 성공/실패 조건과 rollback 조건을 확인한다.

### 내가 실기기 테스트 전에 결정할 것

- [ ] bounded physical movement scope를 승인한다.
- [ ] physical limits를 authoritative source와 함께 승인한다.
- [ ] production motion profile을 승인한다.
- [ ] PRESET을 명시적으로 허용하거나 제외한다.
- [ ] emergency responsibility, restart criteria, recovery criteria를 문서화한다.
- [ ] 현장 telemetry와 success criteria를 정의한다.

### 내가 현장에서 관찰할 것

- [ ] 승인된 환경과 supervising adult가 유지되는지 확인한다.
- [ ] Agent/Server/Robot identity와 ownership 상태가 일치하는지 확인한다.
- [ ] command/result agreement와 lifecycle 상태를 기록한다.
- [ ] telemetry loss, connection instability, duplicate/replay가 없는지 확인한다.
- [ ] timestamp와 observed behavior를 validation record에 기록한다.

### 이상 시 내가 중단 판단해야 할 조건

- [ ] 예상과 다른 physical behavior
- [ ] command acknowledgement 또는 result 불일치
- [ ] telemetry loss 또는 상태 해석 불가
- [ ] connection instability
- [ ] duplicate/replay 의심
- [ ] 승인되지 않은 command/profile/PRESET 시도
- [ ] supervising adult 또는 equipment owner의 중단 요청
- [ ] 환경이 안전하지 않다고 판단되는 경우

이상 발생 후에는 원인과 cleanup을 기록하고, 명시적인 재개 결정 전까지 재시도하지
않는다. 이 checklist는 실제 구동 명령이나 movement sequence를 제공하지 않는다.

### 테스트 후 학생에게 요구할 evidence

- [ ] validation timestamp
- [ ] Agent/Server SHA
- [ ] 승인된 scope와 제외 scope
- [ ] observed behavior와 expected behavior
- [ ] unexpected behavior 또는 abort 여부
- [ ] telemetry/observability 관찰
- [ ] cleanup/disable/rollback 결과
- [ ] follow-up issue 또는 incident reference
- [ ] SN, UUID, token, password가 redacted됐는지 확인

## Software Validation Results

### Poppy-agent

- harness: `PASS`
- Ruff: `PASS`
- Ruff format: `PASS`
- mypy: `PASS`
- pytest: `271 passed`
- physical execution preflight: `PASS` — 13 software-only phases
- `git diff --check`: `PASS`

실제 SDK, DDS, Robot network, SportClient, publisher/subscriber는 실행하지 않았다.

### Poppy-Server

- latest develop assemble: `PASS`
- Docker-independent domain/contract test subset: `PASS`
- full `./gradlew test`: `BLOCKED` by environment
- cause: Testcontainers가 Docker socket `/var/run/docker.sock`에 접근할 권한이 없음
- code defect classification: `NONE CONFIRMED`

Server full integration test를 통과했다고 표현하지 않는다. Docker 접근 권한을 가진
승인된 software-only 환경에서 별도로 재실행해야 한다.

## Deployment Handoff

- #89: `OPEN`
- deployment approval: `PROVIDED`
- deployment execution: `NOT_STARTED`
- deployed Agent: `d6fc2f1acab258c200583f1fc946a44eea29fb42`
- target Agent: `8a75d0635f035f6eb47969d3196c4dc8c2f28ada`
- drift: 57 behind, 0 ahead
- rollback reference: deployed SHA `d6fc2f1...` plus protected EnvironmentFile/config backup
- readiness: `READY_FOR_AUTHORIZED_DEPLOYMENT`

이 판정은 deployment 준비 상태이며 `DEPLOYED` 또는 `PHYSICAL_READY`를 의미하지
않는다. 실제 deployment는 별도의 승인된 실행 단계에서 수행한다.

## Risk Review

| Risk | Severity | Current assessment |
| --- | --- | --- |
| physical command가 gate를 우회 | `LOW` | factory가 client보다 먼저 gate를 평가하며 tests가 blocked path에서 factory 0을 확인 |
| default-disabled가 실제 fail-closed가 아님 | `LOW` | flag만으로 gate 통과 불가; readiness evidence 전체 필요 |
| Mock과 real path 혼동 | `MEDIUM` | Mock은 trace-only지만 문서·validation record에서 분리해 기록해야 함 |
| STOP 의미 혼동 | `HIGH` | Program STOP은 physical emergency stop이 아님; 현장 procedure 별도 필요 |
| duplicate/replay | `LOW` | recovery/reconciliation과 preflight가 replay 0을 검증 |
| connection loss | `MEDIUM` | degraded/cancellation/reconciliation은 software로 처리되나 field evidence 없음 |
| startup/shutdown failure | `MEDIUM` | fail-closed/error normalization은 검증됐지만 production deployment는 stale |
| secret 노출 | `LOW` | secret-safe logging/tests와 role-only 기록 정책 존재 |
| stale deployment | `HIGH` | deployed Agent가 57 commits behind이고 current safety baseline을 포함하지 않음 |
| field observability 부족 | `HIGH` | software snapshot은 있으나 hardware telemetry/physical health evidence 없음 |

## Current Decision

```text
Physical Readiness: BLOCKED
Physical execution: NOT READY FOR PHYSICAL EXECUTION
Hardware validation: NOT TESTED ON HARDWARE
Deployment handoff: READY_FOR_AUTHORIZED_DEPLOYMENT
```

## Recommended Next Action

Docker/Testcontainers 접근 권한이 있는 승인된 software-only 환경에서 Poppy-Server
전체 integration test를 재실행하고 그 결과를 #89 handoff에 추가한다. 이 작업은
deployment와 Robot hardware operation을 포함하지 않는다.

## Safety

- Robot network accessed: `NO`
- DDS initialized: `NO`
- SportClient: `NO`
- publisher/subscriber: `NO`
- Agent service changed: `NO`
- production deployment changed: `NO`
- physical execution enabled: `NO`
- physical command: `NO`
- Robot movement: `NO`
