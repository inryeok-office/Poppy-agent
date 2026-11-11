# 시간 제한 open 모드 (`controlled_motion_open`)

장비 책임자(교사)가 2026-10-28 20:20부터 2시간 동안 블록 반복 시험을 허용했다(교사 2차 승인).
2026-10-29 교사 승인이 하루 최대 8시간으로 연장돼, 만료 시각 상한을 Agent 시작 시점 기준 8시간 5분으로 올렸다
(boot gate·전환 스크립트도 같은 상한).
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
| `POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S` | (선택) 기본 `2.0` | 0 이상 15 이하, `0` 이면 끔 |
| `POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S` | (선택) 기본 `2.0` | 0 이상 15 이하, `0` 이면 사전 BalanceStand 를 끔 |
| `POPPY_PHYSICAL_APPROVAL_REF` | 승인 기록 식별자 | 출력 가능 120자 |
| `POPPY_PHYSICAL_TRIAL_EXPIRES_AT` | 만료 시각(ISO 8601, offset 필수) | 시작 시점 기준 미래, 8시간 5분 이내 (2026-10-29 교사 승인 최대 8시간으로 연장) |

- 기본값은 없다. 누락·범위 밖이면 BLOCKED, heartbeat-only(`UNAVAILABLE`).
- 만료 후에는 모든 실행을 거부하고 status는 `BLOCKED`(`TRIAL_EXPIRED`), operationalStatus는
  `UNAVAILABLE`이다. 프로세스는 종료하지 않는다.
- 실행 횟수 제한(process budget)이 없다. 결과 불명/SDK 예외는 그 실행만 FAILED이며 `lastFailure`로
  기록하고 LOCKED로 바꾸지 않는다. 자동 retry는 없다.

## 실행 1회 검사(dispatch 전 전체 프로그램)

- MOVE 명령당 ≤ 3.0 m, 총 이동 ≤ 4.0 m. TURN 명령당 ≤ 360°.
- 총 계획 시간(이동 거리/속도 + 회전 각도/각속도 + 자세 settle + preset settle + WAIT) ≤ 120 s.
- SIT 이후 STAND 전까지 MOVE·TURN·PRESET 거부. SIT 상태는 실행 사이에도 유지된다(SIT 명령을
  보낸 순간부터 앉은 것으로 간주, STAND 성공 후 해제).
- PRESET은 allow-list 코드만 허용(`CommandSafetyPolicy`와 guard 두 곳에서 검사).
- STOP 이후 명령은 실행하지 않는다.

## SDK 매핑

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

## 실기 기록

- [2026-10-28](trial-records/2026-10-28.md): TURN·MOVE·SIT→STAND→MOVE 실행, yaw `+1` 검증.
- [2026-10-29](trial-records/2026-10-29.md): r7 `RiseSit` 첫 실행(3회 성공), PRESET `HEART` 성공.

## 배포·전환 (운영자 TTY)

- 배포: `/home/poppy/prepared/` 의 r7 배포 스크립트(physical=false 로 배포, 자동 롤백·재시작 보류 규칙).
- 전환: `poppy-agent-open-trial-switch.sh on|off|check` — `on` 은 만료 시각을 넣고 physical=true 로
  재시작한 뒤 READY 를 확인, `off` 는 physical=false 로 되돌린다.

## 이동 직후 PRESET·POSTURE 전 정지 대기 (#120)

2026-11-11 실기에서 MOVE 가 끝나고 0.1초 뒤 보낸 HELLO 를 SDK 가 거절했다(로봇이 아직 멈추는 중).
PRESET·POSTURE 는 직전에 MOVE·TURN 이 있었으면 **모션이 끝난 시각부터** `POPPY_PHYSICAL_SETTLE_BEFORE_ACTION_S`
초(기본 2.0) 지난 뒤에 보낸다.

- 모션 종료와 명령 사이에 WAIT 블록이 있으면 그 시간은 이미 기다린 것으로 센다(모자란 만큼만 더 기다린다).
- 한 번의 모션 뒤에는 한 번만 기다린다(인사 → 하트처럼 이어지는 PRESET 앞에서 다시 기다리지 않는다).
- 이 대기 중 취소하면 로봇에 아무 명령도 보내지 않고 취소된다.
- **실행 시간 상한(`POPPY_PHYSICAL_MAX_TOTAL_SECONDS`) 계산에 넣지 않는다.** 상한은 계획된 모션 시간의 합이고, 이 대기는 로봇이 정지한 유휴 시간이다.
- 설정하지 않아도 기본 2.0초로 동작한다. 잘못된 값(음수·숫자 아님·15 초과)은 실기를 차단하고 사유(`configIssues`)에 보인다.
- 읽기 전용 속도 값을 줄 수 있는 어댑터(예: `rt/sportmodestate`)가 연결되면 `OpenMotionActions.speed_probe` 로
  고정 대기 대신 "속도 0.05 m/s 미만이 될 때까지, 최소 0.3초·최대 3초, 0.1초 간격"으로 기다리고,
  최대를 넘기면 `execution_physical_settle`(`MAX_WAIT_EXCEEDED`) 경고를 남기고 진행한다.
  develop 에서는 `rt/lowstate` 만 구독하므로 아직 연결되어 있지 않다.
- 로그: `execution_physical_settle` (`action`, `execution_status`=`SETTLED`/`MAX_WAIT_EXCEEDED`, `elapsed_seconds`).

### 이동 뒤 PRESET 은 BalanceStand 로 기본 자세를 먼저 잡는다 (#120, 2차)

같은 날 1초 대기를 넣고 다시 돌린 실기 로그: 대기는 정확히 반영됐는데 `HELLO` 가 **시작 5.0초 뒤** `FAILED` 였다
(`Hello,BalanceStand` 중 Hello 를 보내고 5초 정착 대기를 거친 뒤 **뒤따르는 BalanceStand** 가 실패한 것과 같은 시각).
인사만 단독으로는 성공한다. 그래서 이동·회전 직후의 PRESET 은 다음 순서로 보낸다.

```
(정지 대기) → BalanceStand → 대기(POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S, 기본 2.0) → PRESET → 정착 대기 → BalanceStand
```

- 직전에 MOVE·TURN 이 없었으면 예전 그대로 `PRESET → 정착 대기 → BalanceStand`(인사 → 하트처럼 이어지는 PRESET 도 그대로).
- 사전 BalanceStand 가 실패하면 PRESET 을 보내지 않고 그 실행을 실패로 끝낸다. 어느 경우든 다음 실행은 막히지 않는다(테스트로 고정).
- `POPPY_PHYSICAL_BALANCE_BEFORE_PRESET_SETTLE_S=0` 이면 사전 BalanceStand 를 끄고 1차 수정(정지 대기만) 동작으로 돌아간다.
- **호출 단위 로그** `execution_physical_sdk_call`: 어떤 SDK 호출(`sdk_operation`)이 `OK`/`FAILED` 였는지와 SDK 반환 코드(`sdk_result_code`)를
  한 줄씩 남긴다(`Move`·`StopMove` 는 모션 요약 로그가 있어 제외). 실패한 호출이 Hello 인지 BalanceStand 인지 이 로그로 구분한다.
- 자세·모드를 읽는 텔레메트리(`rt/sportmodestate`)는 develop 에서 구독하지 않아 "기본 자세가 된 것을 확인하고 진행"은 아직 못 한다.
  연결되면 사전 BalanceStand 뒤의 고정 대기를 그 확인으로 바꾼다(후속).

### PRESET 호출 전용 SDK 대기 시간 60초와 실패 뒤 10초 보류 (#120, 3차)

2026-11-11 실기: Dance1 이 `SDK_RC_3104`(클라이언트 10초 타임아웃)로 실패 보고됐지만 **로봇은 실제로 춤을 췄다.**
PRESET 호출은 로봇이 동작을 끝낼 때까지 막히는 호출이다(실측 Hello 약 4.1초, Heart 약 5.3초, Dance1 10초 초과).
또 이동 → 하트가 한 번 `SDK_RC_4201`(`SPORT_ERR_SERVER_OVERTIME`, 로봇 sport 서버가 돌려준 오류)로 실패했고 39초 뒤 같은 구성이 성공했다.

- PRESET 호출에만 SDK 응답 대기를 **60초**(`PRESET_RPC_TIMEOUT_SECONDS`)로 늘리고, 호출이 끝나면(예외 포함) 원래 값(10초)으로 되돌린다.
  `Move`·`BalanceStand` 등 다른 호출의 대기 시간은 바뀌지 않는다. 클라이언트 대기 시간이 설정되지 않았거나 이미 60초 이상이면 건드리지 않는다.
- PRESET 이 **실패하면 10초간**(`OpenMotionActions.preset_failure_hold_seconds`) 다음 물리 명령(MOVE·TURN·POSTURE·PRESET)을 보내지 않는다.
  타임아웃이든 서버 오류든 실패는 로봇이 멈췄다는 뜻이 아니다. 실패 시각부터 계산하므로 그 사이에 지난 시간은 차감하고,
  보류 중 취소하면 아무것도 보내지 않는다. STOP 은 보류하지 않는다.
- `UnitreeSdkCommandClient.last_result_code`: 마지막 SDK 호출의 정수 반환 코드(없으면 `None`).
- 4201 의 원인은 아직 모른다. 이 수정은 4201 자체를 막지 않고, 실패한 PRESET 이 진행 중일 때 다음 명령이 겹치지 않게만 한다.
- 실기 검증 필요(로봇 없이는 위 대기 시간이 실제 로봇에서 충분한지 확인할 수 없다).
