# 원클릭 행사 시작 (`scripts/event_start.py`, #100)

운영 노트북에서 운영자가 TTY 로 실행한다. AI 에이전트는 dry-run 과 fake 테스트만 수행한다.

## 순서

1. `systemctl show poppy-agent` 로 상태 확인 → `failed` 면 `reset-failed` + `start`, `inactive` 면 `start`,
   `active` 면 그대로. 그 밖의 상태는 FAIL(수동 확인).
2. `deploy/systemd/poppy-agent.service.d/10-event-no-restart.conf`(`Restart=no`)가
   `/etc/systemd/system/poppy-agent.service.d/` 에 없거나 다르면 설치 후 `daemon-reload`. 디스크의 drop-in
   이라 재부팅 뒤에도 유지된다. 비정상 종료 뒤 자동 재시작으로 실제 동작이 다시 켜지지 않게 한다.
3. 로봇 늦은 기동 대기: `/run/poppy-agent/status.json` 의 `lifecycleState=READY` 와 `telemetry.fresh=true`
   를 `--poll-seconds`(기본 5 s) 간격으로 `--wait-seconds`(기본 180 s)까지 재시도.
4. 승인 만료 검사: `TRIAL_EXPIRED`, `EXPIRES_AT` 설정 오류, 남은 시간 30분 이하면 FAIL. 만료 시각을
   바꾸거나 우회하지 않는다(교사 승인 갱신 후 켜기 스크립트가 새 만료 시각을 쓴다).
5. 오래된 대기 실행 정리 확인: Server 쪽 정리(Poppy-Server#132) 후 운영자가 `--queue-cleared` 를 줘야
   다음 단계로 간다.
6. 켜기: `--switch-command '<켜기 스크립트> on'` 을 실행하고 `physicalExecution.state=READY` 까지 대기.
   지정하지 않으면 `MANUAL` 로 끝난다.

마지막 줄은 한 줄 결과다: `OK: ...`, `DRY-RUN OK: ...`, `MANUAL: ...`, `FAIL: <원인과 조치>`.
FAIL 이면 exit code 1.

## 사용

```bash
# 기본은 dry-run: 아무 명령도 실행하지 않고 출력만 한다
python3 scripts/event_start.py --queue-cleared --switch-command '<켜기 스크립트> on'

# 실제 실행(운영자)
python3 scripts/event_start.py --execute --queue-cleared --switch-command '<켜기 스크립트> on'
```

dry-run 은 `--simulate-state failed|inactive|active`, `--simulate-drop-in` 으로 가정 상태를 바꿀 수 있고,
`--status-path` 로 fixture 스냅샷을 줄 수 있다.

## 한계

- EnvironmentFile 은 읽지 않는다. physical off 상태에서는 만료 시각이 스냅샷에 없으므로 승인 검사는
  켜기 스크립트와 켜기 후 READY 확인에 맡긴다.
- 대기 실행 정리는 Server API 계약이 정해지지 않아(Poppy-Server#132) 운영자 확인 플래그로 대신한다.
- `Restart=no` 이므로 Agent 가 죽으면 이 스크립트를 다시 실행해 상태를 확인하며 시작한다.
