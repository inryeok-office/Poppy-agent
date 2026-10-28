# 통제된 첫 TURN 시험 모드 (`controlled_turn_v1`)

Issue #92. 장비 책임자(교사) 입회 하에 GO2 EDU 한 대로 왼쪽 6° 제자리 회전을 1회 수행하기
위한 Agent 경로다. 절차 요건은 `AGENTS.md`의 "Controlled physical trial exception"을 따른다.

## 시험 수치와 출처

| 설정 키 | 시험 값 | 출처 | 코드 상한 |
|---|---|---|---|
| `POPPY_PHYSICAL_TRIAL_MODE` | `controlled_turn_v1` | 이 문서 | 정확히 일치 |
| `POPPY_PHYSICAL_TURN_RATE_DEG_PER_S` | `6` (= 0.1047 rad/s) | 시험 제안값(관리자 원문 아님) | 0.8 rad/s(≈45.84°/s) 이하 |
| `POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND` | `6` | 시험 제안값 | 누적 회전 상한 이하 |
| `POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG` | `360` | 관리자 원문(사용자 전달) | 360 이하 |
| `POPPY_PHYSICAL_MAX_TOTAL_SECONDS` | `60` | 관리자 원문(사용자 전달) | 60 이하 |
| `POPPY_PHYSICAL_MAX_COMMANDS` | `1` | 시험 제안값 | 1 이상 정수 |
| `POPPY_PHYSICAL_ALLOWED_COMMANDS` | `TURN` | 시험 범위 | 정확히 `TURN` |
| `POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN` | `+1` 또는 `-1` | 아래 "yaw 부호" 참고 | `+1`/`-1` |
| `POPPY_PHYSICAL_APPROVAL_REF` | 승인 기록 식별자 | 장비 책임자 승인 | 출력 가능 문자 120자 이하 |

- 관리자 원문의 선속도 상한 3 m/s는 TURN에 쓰지 않는다(TURN의 선속도는 0).
- GO2 EDU high-level `vyaw` 범위 [-0.8, 0.8] rad/s는 V1.1.6 미만 인터페이스 문서 기준이며
  장비 readback 값이 아니다.
- 기본값은 없다. `POPPY_ENABLE_PHYSICAL_EXECUTION=true`인데 키가 없거나 범위 밖이면
  물리 실행은 BLOCKED이고, Agent는 종료하지 않고 heartbeat-only(`UNAVAILABLE`)로 계속 동작한다.

## yaw 부호

`LEFT → vyaw = +rate × SIGN`, `RIGHT → vyaw = -rate × SIGN`. 양수 `vyaw`가 실제로 반시계(왼쪽)
회전인지는 이 프로젝트에서 장비로 확인하지 않았다. `+1`은 일반 관례에 따른 **미검증 가정**이며,
시험 결과로 관찰된 방향을 아래 기록 절에 남긴 뒤 이 문서를 갱신한다.

## 실행 경로

1. Server v1 배달 → parser → `ExecutionSafetyValidator`
2. `TrialGuard.admit`(프로그램 전체 사전 검사, dispatch 전 budget 차감, 환불 없음)
   - 물리 명령은 TURN만 허용. MOVE·POSTURE·PRESET이 있으면 거부. WAIT·STOP은 허용
     (STOP은 프로그램 종료이며 `StopMove`가 아니다).
   - TURN 개수, 명령당 각도, 누적 각도, 누적 시간(각도 ÷ 각속도)을 검사한다.
   - telemetry가 fresh가 아니면 budget을 쓰지 않고 거부한다.
3. `UnitreeCommandBackend` → `MotionExecutionStrategy`(각속도 = 설정값, MOVE 미설정)
   → `Go2TurnRateMapper` → `UnitreeSdkCommandClient.execute_motion_with_cancellation`
4. SDK client가 이동 시간을 소유한다: `Move(0, 0, vyaw)`를 50ms 주기로 반복 전송하고,
   계획 시간 이후에는 새 `Move`를 시작하지 않는다. 각 주기마다 취소를 확인한다.
   종료·취소·예외 어느 경우든 `StopMove`를 50ms 간격으로 3회 best-effort 전송한다.
5. 결과 불명(Move 예외, Move 1회 호출 0.5초 이상, `StopMove` 성공 0회) → 실행 FAILED,
   `TrialGuard` LOCKED. 재시작 전까지 모든 물리 명령을 거부한다.

6° TURN은 계획 시간 1.0초, `Move` 20회, `StopMove` 3회다(fake 시계 테스트로 확인).

## Readiness evidence

`PhysicalReadinessEvidence`는 설정에서만 만들어진다(`controlled_trial_readiness_evidence`).
`create_controlled_trial_executor`는 evidence 인자를 받지 않는다.

- `command_client_kind=REAL`: 실제 `UnitreeSdkCommandClient` adapter를 사용할 때만.
- 승인 관련 항목: `POPPY_PHYSICAL_APPROVAL_REF`가 있을 때만 true.
- `telemetry_requirements_met`: freshness 검사가 연결됐다는 의미이며, 실제 freshness는
  admission 시점과 operationalStatus에서 매번 확인한다.
- `hardware_validation_completed`는 false로 남는다. 이번 시험 자체가 첫 hardware
  validation이므로 trial mode에서만 `controlled_trial_budget_defined`(MAX_COMMANDS ≥ 1)가
  이 blocker를 대신한다. 일반 evidence의 기본값은 이 대체를 허용하지 않는다.

## Server 보고

- capability는 항상 `TELEMETRY`, `COMMAND_TURN`을 보고한다. Server에 `COMMAND_TURN`이
  등록된 뒤 보고에서 빠지면 등록이 실패(`AGENT_COMPATIBILITY_INVALID`)하기 때문이다.
- operationalStatus `READY` 조건: physical enabled, 설정 완전, readiness READY(executor
  생성됨), telemetry fresh, trial budget 남음, 실행 중이 아님, active execution 없음.
  하나라도 아니면 `UNAVAILABLE`. budget 소진·LOCKED 후에는 계속 `UNAVAILABLE`이다.

## 상태 파일

`POPPY_RUNTIME_STATUS_PATH`의 JSON에 `physicalExecution`이 추가된다.

- 비활성/차단: `{"enabled": false|true, "state": "BLOCKED", "reasons": [...], "configIssues": [...]}`
- 활성: `state`(`READY`/`NOT_READY`), `mode`, `turnRateDegreesPerSecond`,
  `maxTurnDegreesPerCommand`, `turnLeftYawSign`, `trial`(`state`, `commandsUsed`,
  `commandsMax`, `turnDegreesUsed`, `motionSecondsUsed`, `lockReason`, `approvalRef`).

## 로그

`physical_execution_blocked`, `physical_execution_enabled`,
`execution_physical_turn_started`, `execution_physical_turn_finished`,
`execution_physical_trial_locked` 이벤트에 command type, 방향, 각도, `vyaw`, duration,
Move/StopMove 횟수, trial 잔여 budget, approval ref를 남긴다. 토큰 등 비밀값은 남기지 않는다.

## 알려진 한계

- `Move`는 SDK에서 응답 없는 호출(`_CallNoReply`)이라 Robot이 명령을 받았는지 확인할 수
  없다. 0.5초 검사는 호출이 돌아온 뒤 판정한다(호출 자체를 중단하지는 못한다).
- `Move` 명령 만료 동작은 확인되지 않아 주기 전송과 `StopMove` 3회로 대비한다.
- `StopMove`는 하드웨어 비상정지가 아니다. 비상 시에는 리모컨 Damping을 사용한다.

## 시험 기록

시험 후 관찰된 회전 방향, 대략 각도, 정지 여부, 실행 상태, Server 실행 ID, Agent 로그 요약을
별도 기록 문서로 추가한다(현장 개인정보·IP 제외).
