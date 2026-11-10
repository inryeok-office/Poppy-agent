# 명령값 대 실제 이동 데이터셋 (#102)

#99 실측(docs/r11-closed-loop-field-validation.md)과 Agent 로그를 묶어 움직임 보정(#106) 학습용 CSV 를 만든다.
로봇·서비스에 접근하지 않는 오프라인 변환이다.

## 만들기

```bash
journalctl -u poppy-agent -o cat --since '2026-11-12 09:00' > agent.log   # 운영자
python3 scripts/motion_dataset_export.py agent.log --measurements measured.csv --output dataset.csv
```

stderr 에 `rows=N missing_measurement=M` 을 출력한다. 실측이 없는 행도 버리지 않고 `missing_measurement=1` 로 남긴다.

## 실측 CSV (현장 기록)

| 열 | 의미 |
|---|---|
| `execution_id` | 실행 ID 전체 또는 앞 8자 |
| `motion_index` | 그 실행 안의 MOVE·TURN 순번(1부터, WAIT·자세·프리셋 제외) |
| `measured` | 실측값. MOVE 는 m, TURN 은 ° (명령 단위와 같음) |
| `lateral_cm` | MOVE 옆 이탈(cm), 없으면 빈칸 |
| `surface` | 바닥 종류(예: `mat`, `wood`) |
| `note` | 비고(개인정보 금지) |

## 출력 열

`timestamp`, `execution_id`, `motion_index`, `command_type`, `direction`, `commanded`, `unit`(`m`/`deg`),
`command_rate`(MOVE `vx` m/s, TURN `vyaw` rad/s), `planned_seconds`, `elapsed_seconds`, `stop_move_successes`,
`motion_status`, `achieved`(#97 폐루프의 `StopMove` 직전 도달값, 없으면 빈칸), `measured`, `error`(= measured − commanded),
`lateral_cm`, `surface`, `note`, `missing_measurement`.

- 실행 단위 연결: 각 동작 행은 직전 `execution_started` 의 `execution_id` 에 붙는다.
- 신선도·실패: `motion_status` 가 `FAILED`/`CANCELLED` 인 행도 남긴다. 학습 때 거를지는 사용하는 쪽이 정한다.

## 개인정보·비밀

Agent 로그의 allow-list 필드만 읽는다. `agent_id`, `robot_id`, `approval_ref`, IP, 토큰, 사람 이름·사진은 출력하지 않는다.
데이터셋 파일은 저장소에 커밋하지 않고 `~/poppy-ai/data` 에 둔다.
