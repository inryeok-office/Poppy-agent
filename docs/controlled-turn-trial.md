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
| `POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN` | `+1` | 2026-10-28 실기 검증(아래 "yaw 부호") | `+1`/`-1` |
| `POPPY_PHYSICAL_APPROVAL_REF` | 승인 기록 식별자 | 장비 책임자 승인 | 출력 가능 문자 120자 이하 |

- 관리자 원문의 선속도 상한 3 m/s는 TURN에 쓰지 않는다(TURN의 선속도는 0).
- GO2 EDU high-level `vyaw` 범위 [-0.8, 0.8] rad/s는 V1.1.6 미만 인터페이스 문서 기준이며
  장비 readback 값이 아니다.
- 기본값은 없다. `POPPY_ENABLE_PHYSICAL_EXECUTION=true`인데 키가 없거나 범위 밖이면
  물리 실행은 BLOCKED이고, Agent는 종료하지 않고 heartbeat-only(`UNAVAILABLE`)로 계속 동작한다.

## yaw 부호

`LEFT → vyaw = +rate × SIGN`, `RIGHT → vyaw = -rate × SIGN`.

**`+1`, 2026-10-28 실기 검증.** `controlled_motion_open` 시험에서 웹 블록 "오른쪽 30°"
(`TURN RIGHT`, SIGN `+1` → `vyaw` 음수)를 실행했을 때 GO2 EDU가 위에서 볼 때 시계 방향(오른쪽)으로
회전했다. 따라서 양수 `vyaw`는 반시계(왼쪽) 회전이며 `POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN=+1`이
맞다. 이 값은 설정으로 유지한다(펌웨어·장비가 바뀌면 다시 검증한다).

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

## boot gate(ExecStartPre)

운영 unit의 `ExecStartPre` boot gate(`/usr/local/libexec/poppy-agent-boot-gate.sh`)는 원래
`POPPY_ENABLE_PHYSICAL_EXECUTION`이 정확히 `false`가 아니면 Agent 시작을 거부한다. r5 배포
스크립트는 이 검사를 바꾸지 않으므로, physical=true로 재시작하기 전에 trial용 boot gate를 먼저
설치해야 한다(r5 첫 시험에서 gate가 시작을 거부해 확인됨, 로봇 명령 없음).

trial boot gate는 physical=true를 다음을 모두 만족할 때만 허용하고, 허용 시 journal에
`WARNING: physical execution enabled for controlled_turn_v1 trial`을 한 줄 남긴다. 그 외에는
기존과 같이 `ERROR: physical execution must be false.`로 거부한다. NIC·route·Server health
검사는 그대로다.

- 시험 키 9개가 모두 비어 있지 않게 설정됨
- `POPPY_PHYSICAL_TRIAL_MODE=controlled_turn_v1`, `POPPY_PHYSICAL_MAX_COMMANDS=1`,
  `POPPY_PHYSICAL_ALLOWED_COMMANDS=TURN`, `POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND=6` 정확히 일치

boot gate는 service user로 실행되고 EnvironmentFile 디렉터리는 root 전용이라, gate는 systemd가
넘긴 실제 환경값만 검사한다. EnvironmentFile의 키별 줄 수(각 1줄, `POPPY_PHYSICAL_*` 총 9줄)는
재시작 직전 root가 읽기 전용 사전 확인 스크립트로 검사한다(값은 출력하지 않는다).

절차(모두 운영자 TTY):

1. `sudo bash /home/poppy/prepared/poppy-agent-boot-gate-trial-apply.sh`: 기존 gate를
   `/root/poppy-agent-backups/<시각>-boot-gate-trial-prechange/`에 백업하고, 원본과 같은
   소유자·권한으로 새 gate를 설치한 뒤 `bash -n`과 physical=false 상태의 gate 1회 실행(exit 0)을
   확인한다. Agent는 재시작하지 않는다. 실패하면 백업으로 자동 복원한다.
2. physical=true로 바꾼 뒤 `sudo bash /home/poppy/prepared/poppy-agent-trial-env-precheck.sh true`가
   `RESULT: OK`일 때만 재시작한다.
3. 시험 후 physical=false로 되돌리고 `... precheck.sh false`로 확인한 뒤 재시작한다.
4. gate 되돌리기: 적용 스크립트가 출력한 `revert:` 명령(백업에서 `install -p`로 복원).

## r5에서 r4로 롤백할 때

r5가 Server에 등록되면 GO2EDU001의 capability 목록에 `COMMAND_TURN` 키가 추가될 수 있다.
Server의 `RobotManagementService`는 재등록 시 Agent가 보고하는 capability 집합이 Robot에
등록된 키 집합을 포함하는지 검사한다. r4는 `COMMAND_TURN`을 보고하지 않으므로 이 키가
남아 있으면 r4 재등록이 실패할 수 있다.

자동 롤백은 백업의 r4 release, unit/drop-in 및 EnvironmentFile을 복원한다. r5 등록 성공이
확인됐거나 등록 여부를 확정할 수 없으면 r4를 자동 시작하지 않고 중지 상태로 둔다. 롤백
출력의 **ACTION REQUIRED BEFORE STARTING R4** 안내를 따른다.

1. 관리자 TTY에서 `/home/poppy/prepared/poppy-robot-command-turn-capability.py remove`를
   실행한다. 이 모드는 GO2EDU001을 GET한 뒤 현재 목록에서 `COMMAND_TURN` 항목만 제거한
   전체 목록을 PATCH하고 다시 GET해 확인한다.
2. `COMMAND_TURN`이 목록에서 사라졌고 나머지 capability 항목이 보존됐는지 확인한다.
3. 그 후에만 승인된 절차로 r4 Agent를 시작한다.

`revert`는 `COMMAND_TURN` 상태를 `UNVERIFIED`로 바꿀 뿐 키 자체를 제거하지 않는다. 따라서
r4 재등록 호환성 복구에는 `revert`가 아니라 `remove`를 사용해야 한다. 자동 롤백에서 등록
거부가 명확히 확인된 경우에만 기존 절차대로 r4 시작을 시도한다. 로그 증거가 없거나
불명확한 경우도 등록 가능성이 남은 것으로 보고 자동 시작을 보류한다.

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

## 시간 제한 open 모드 (`controlled_motion_open`)

장비 책임자(교사)가 2026-10-28 20:20부터 2시간 동안 블록 반복 시험을 허용했다(교사 2차 승인).
`controlled_turn_v1`은 그대로 두고 별도 모드로 추가한다. 관리자 원문(누적 회전 360°, 선속도
3 m/s, 60 s)과 이번 교사 승인(실행 1회 기준 총 이동 4.0 m, 총 동작 시간 120 s)은 출처가
다르며, 아래 하드 상한은 교사 승인 값이다.

| 설정 키 | 시험 값 | 코드 하드 상한 |
|---|---|---|
| `POPPY_PHYSICAL_TRIAL_MODE` | `controlled_motion_open` | 정확히 일치 |
| `POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S` | `0.5` | 1.0 |
| `POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND` | `3.0` | 총 이동 상한 이하 |
| `POPPY_PHYSICAL_MAX_TOTAL_MOVE_M` | `4.0` | 4.0 (실행 1회) |
| `POPPY_PHYSICAL_TURN_RATE_DEG_PER_S` | `45` (0.785 rad/s) | 0.8 rad/s |
| `POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND` | `360` | 360 |
| `POPPY_PHYSICAL_MAX_TOTAL_SECONDS` | `120` | 120 (실행 1회) |
| `POPPY_PHYSICAL_POSTURE_SETTLE_SECONDS` | `3` | 15 |
| `POPPY_PHYSICAL_PRESET_SETTLE_SECONDS` | `5` | 15 |
| `POPPY_PHYSICAL_ALLOWED_COMMANDS` | `MOVE,TURN,POSTURE,PRESET` | 이 네 값의 부분집합 |
| `POPPY_PHYSICAL_ALLOWED_PRESETS` | `HELLO,STRETCH,HEART,DANCE1` | 아래 매핑 표의 부분집합 |
| `POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN` | `+1` (2026-10-28 실기 검증) | `+1`/`-1` |
| `POPPY_PHYSICAL_APPROVAL_REF` | 승인 기록 식별자 | 출력 가능 120자 |
| `POPPY_PHYSICAL_TRIAL_EXPIRES_AT` | 만료 시각(ISO 8601, offset 필수) | 시작 시점 기준 미래, 2시간 5분 이내 |

- 기본값은 없다. 누락·범위 밖이면 BLOCKED, heartbeat-only(`UNAVAILABLE`).
- 만료 후에는 모든 실행을 거부하고 status는 `BLOCKED`(`TRIAL_EXPIRED`), operationalStatus는
  `UNAVAILABLE`이다. 프로세스는 종료하지 않는다.
- 실행 횟수 제한(process budget)이 없다. 결과 불명/SDK 예외는 그 실행만 FAILED이며 `lastFailure`로
  기록하고 LOCKED로 바꾸지 않는다. 자동 retry는 없다.

### 실행 1회 검사(dispatch 전 전체 프로그램)

- MOVE 명령당 ≤ 3.0 m, 총 이동 ≤ 4.0 m. TURN 명령당 ≤ 360°.
- 총 계획 시간(이동 거리/속도 + 회전 각도/각속도 + 자세 settle + preset settle + WAIT) ≤ 120 s.
- SIT 이후 STAND 전까지 MOVE·TURN·PRESET 거부. SIT 상태는 실행 사이에도 유지된다(SIT 명령을
  보낸 순간부터 앉은 것으로 간주, STAND 성공 후 해제).
- PRESET은 allow-list 코드만 허용(`CommandSafetyPolicy`와 guard 두 곳에서 검사).
- STOP 이후 명령은 실행하지 않는다.

### SDK 매핑

| Poppy | SDK 호출 | 근거 |
|---|---|---|
| MOVE FORWARD/BACKWARD | `Move(±speed, 0, 0)` 50 ms 반복, 종료·취소·예외 시 `StopMove` 3회 | `sport_client.py:132` |
| TURN LEFT/RIGHT | `Move(0, 0, ±rate×SIGN)` 동일 | `sport_client.py:132` |
| POSTURE SIT | `Sit` → settle 대기 | `sport_client.py:142` |
| POSTURE STAND (직전 자세 SIT) | `RiseSit` → settle 대기 | `sport_client.py:149`, 예제 `sport_client_example.py:72`, `:81` |
| POSTURE STAND (그 외) | `StandUp` → settle 대기 → `BalanceStand` | `sport_client.py:101`, `:87` |
| PRESET HELLO | `Hello` → settle → `BalanceStand` | `sport_client.py:164` (API 1016) |
| PRESET STRETCH | `Stretch` → settle → `BalanceStand` | `sport_client.py:171` (API 1017) |
| PRESET DANCE1 | `Dance1` → settle → `BalanceStand` | `sport_client.py:185` (API 1022) |
| PRESET HEART | `Heart` → settle → `BalanceStand` | `sport_client.py:243` (API 1036) |
| WAIT | 취소 가능한 대기 | - |

- 점프·플립·포운스·구르기 계열(`FrontFlip`, `FrontJump`, `FrontPounce`, `BackFlip`, `LeftFlip`,
  `HandStand` 등)은 매핑하지 않으며 SDK client도 allow-list 밖 메서드를 호출하지 않는다.
- SDK 소스에는 자세·preset 완료 신호와 `StandUp` 후 `Move` 수신 조건에 대한 설명이 없다
  (`sport_client.py`는 RPC 래퍼뿐). 그래서 고정 settle 대기 후 `BalanceStand`를 호출한다. 이 순서가
  필요한지는 장비에서 확인되지 않은 가정이다. SIT 직후의 STAND는 SDK 테스트 예제가 `Sit` 다음에
  `RiseSit`을 쓰는 것(`unitree_sdk2py/test/client/sport_client_example.py:72`, `:81`)을 따라
  `RiseSit`으로 매핑한다. 직전 자세는 Agent 프로세스가 추적한 값(SIT 전송 시점부터 앉음)이다.
- RPC timeout은 공식 예제와 같은 10 s(`example/go2/high_level/go2_sport_client.py:84`), SDK 기본은
  1 s(`rpc/client_base.py:20`).
- capability는 항상 `TELEMETRY`, `COMMAND_TURN`, `COMMAND_MOVE`, `COMMAND_STOP`,
  `COMMAND_POSTURE`, `COMMAND_PRESET`을 보고한다. r6 → r5/r4 롤백 시에는 capability 스크립트
  `remove-all`로 추가 키를 먼저 제거한다.
