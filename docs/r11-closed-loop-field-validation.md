# r11 폐루프 MOVE·TURN 실측 검증 절차 (#99)

이 문서는 절차와 기록 양식만 정한다. 실행은 사람(운영자)이 하며, AI 에이전트는 로봇 명령·서비스 제어·
EnvironmentFile 수정을 하지 않는다. 대상 구현은 #97(`feature/96-closed-loop-motion`, #95 위 스택)이고,
#96/#97 의 fake 검증과 별개인 실측이다. 기록에는 IP·토큰·로봇 UUID·실명을 적지 않는다.

## 1. 실기 진입 조건 (모두 충족해야 시작)

| # | 조건 | 확인 방법 |
|---|---|---|
| 1 | 교사(장비 담당자) 사전 승인, 현장 입회 | `POPPY_PHYSICAL_APPROVAL_REF` 참조값 기록 |
| 2 | #95 공간 검사 승인 기록 갱신(총 이동 4.0 m → 6 m × 6 m 공간) | #95 코멘트·승인 기록 |
| 3 | 배포 SHA 가 #97 head 와 일치, physical=false 로 배포 후 시작 | 운영 체크아웃 `git rev-parse HEAD` |
| 4 | 관찰자 2명 이상, 리모컨 소지, 주변 비움, Damping 절차 숙지 | CLAUDE.md "Controlled physical trial exception" |
| 5 | 매트 위 출발점·방향 표시(테이프), 줄자(1 cm)·각도 표시(바닥 각도기 또는 90° 기준선) | 사진 1장(사람 없이) |
| 6 | `rt/sportmodestate` 수신 확인: status 의 physical `READY`, 로그에 sport state stale 없음 | `journalctl -u poppy-agent` 요약 |
| 7 | 배터리 50% 이상 | status.json `telemetry.batteryPercent` |

하나라도 빠지면 시작하지 않는다. 시험 중 이상 동작이면 즉시 리모컨 Damping → 3분 대기 → 안전하면 전원 off →
배터리 분리, 해당 회차 `FAILED` 로 기록하고 중단한다.

## 2. 사전 확인 (로봇 정지 상태, 명령 없음)

#97 본문의 미확인 항목을 먼저 기록으로 확인한다.

1. 좌표계: 운영자가 리모컨 보행으로 약 0.5 m 전진시킨 뒤
   로그/구독 기록의 `position` 변화가 시작 yaw 방향과 같은지 본다.
2. yaw 부호: 리모컨으로 왼쪽 회전 시 `imu_state.rpy[2]` 증가/감소를 기록하고 `POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN`
   (10/28 기록 `+1`)과 일치하는지 본다.
3. 수신 주기: 1분간 sport state 수신 간격 최대값을 기록한다(200 ms 신선도 기준 대비).
4. `mode`·`gait_type`: 서 있음/앉음/보행 중 값 기록(#98 `observed_posture()` 매핑 근거로도 쓴다).

## 3. 측정 프로그램

각 회차는 별도 Execution 이다. 회차마다 로봇을 출발 표시 위에, 출발 방향으로 되돌린다(#95 추측 항법 전제).

| 세트 | 프로그램 | 회수 | 목표 |
|---|---|---|---|
| M05 | 전진 0.5 m | 10 | 거리 ±5 cm |
| M10 | 전진 1.0 m | 10 | 거리 ±5 cm |
| M20 | 전진 2.0 m | 10 | 거리 ±5 cm |
| TL90 | 왼쪽 90° | 10 | 각도 ±3° |
| TR90 | 오른쪽 90° | 10 | 각도 ±3° |
| S1 | 미이동 감지: 리모컨 개입 없이 로봇 앞 30 cm 에 부드러운 장애물(폼 블록) | 3 | `StopMove` 후 FAILED, 1.5 s 판정 |

S1 은 교사가 허용할 때만 한다. 충돌 위험이 보이면 생략하고 "생략" 으로 기록한다.

## 4. 측정 방법

- 거리: 출발 표시의 앞발 기준선에서 정지 후 같은 앞발 기준선까지 진행 방향 거리(cm). 옆 이탈(cm)도 함께 잰다.
- 각도: 바닥 기준선 대비 몸통 방향(°). 오른쪽 회전은 시계 방향 양수로 적는다.
- Agent 기록: `execution_physical_turn_finished`(MOVE 포함)의 `achieved_magnitude`, `start_mode`,
  `start_gait_type`, 실행 상태·ID. `achieved_magnitude` 는 `StopMove` 직전 값이라 관성 이동이 빠지므로
  실측과의 차이를 "관성" 으로 따로 계산한다.

## 5. 기록 표 (회차별)

`docs/trial-records/YYYY-MM-DD-r11.md` 에 아래 형식으로 남긴다.

| 세트 | 회차 | 실행 ID(앞 8자) | 상태 | 명령 | 실측 | 오차 | 옆 이탈 | achieved | 관성(실측-achieved) | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|
| M10 | 1 | | COMPLETED | 100 cm | | | | | | |

세트 요약: 평균 오차, 표준편차, 최대 |오차|, 통과 회수(±5 cm / ±3° 이내), FAILED 회수와 사유.

## 6. 판정과 튜닝

- 통과: 각 세트 10회 중 10회가 기준 이내, 미이동 감지(S1)가 FAILED 로 멈춤.
- 평균 오차가 한쪽으로 치우치면(예: 항상 +4 cm) 관성 보정으로 보고 `move_tolerance_meters`/감속 구간
  (`move_slowdown_meters`, `turn_slowdown_degrees`) 조정을 제안한다. 표준편차가 크면 최소 속도
  (`min_linear_speed_meters_per_second`, `min_turn_rate_degrees_per_second`)를 낮추는 방향을 제안한다.
- 값 변경은 별도 PR 로 하고, 바뀐 값으로 해당 세트를 다시 10회 측정한다. 현장에서 코드나 설정을 즉석 수정하지 않는다.
- 결과에 따라 #97 PR 에 "실기 통과/실패" 코멘트를 남기고 `needs-robot-test` 를 해제하거나 유지한다.

## 7. 종료

physical=false 로 되돌리고 READY 가 아님을 확인한다. 기록 문서를 PR 로 올린다.
