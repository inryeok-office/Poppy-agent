# Server Process Restart Recovery

## Purpose

이 문서는 Poppy-Server Spring Boot 프로세스만 재시작하고 PostgreSQL은 유지하는 software-only recovery 계약과 검증 방법을 정의한다. 대상은 Agent runtime의 fail-closed, authoritative Execution reconciliation, Robot ownership release, 재시작 후 새 Execution 처리다.

실제 GO2, Unitree SDK, SportClient, DDS command publisher, physical movement, physical emergency stop은 이 시나리오에 포함하지 않는다. `ROBOT_MODE=mock`만 허용한다.

## Restart 의미

Server application 중지는 데이터베이스 초기화가 아니다. PostgreSQL 데이터는 계속 유지되어야 하며 Session, immutable Block Revision, Simulation Pass, Execution, Agent principal, Robot identity와 credential digest가 보존되어야 한다.

Agent는 Server를 확인할 수 없는 동안 다음 상태를 유지한다.

- connectivity: `DEGRADED`
- operational readiness: `false`
- new Execution polling: disabled
- active Execution: blind continuation 금지
- command replay/progress 추측: 금지

복구 후 Agent는 기존 credential로 Server에 재접속하고, active Execution을 조회한 뒤 현재 recovery contract에 따라 `RUNNING`/`ASSIGNED` Execution을 `FAILED`로 reconcile한다. command payload를 다시 실행하지 않는다.

## 자동 E2E

```powershell
$env:ROBOT_MODE = "mock"
$env:POPPY_SERVER_RESTART_REHEARSAL = "1"
$env:POPPY_E2E_SERVER_URL = "http://localhost:18080"
$env:POPPY_E2E_AGENT_TOKEN = "<local-software-only-token>"
$env:POPPY_SERVER_RESTART_COMMAND_JSON = '["java","-jar","C:/path/to/Poppy-Server-0.0.1-SNAPSHOT.jar","--server.port=18080"]'
python scripts/server_restart_recovery_e2e.py
```

PostgreSQL는 별도로 실행되어 있어야 한다. `POPPY_SERVER_RESTART_DB_HOST`, `POPPY_SERVER_RESTART_DB_PORT`, `POPPY_SERVER_RESTART_DB_NAME`, `POPPY_SERVER_RESTART_DB_USERNAME`, `POPPY_SERVER_RESTART_DB_PASSWORD`로 연결 정보를 지정할 수 있다. 실제 token 값은 shell history, log, snapshot, Issue, PR에 남기지 않는다.

Harness는 시작 전에 대상 localhost port가 이미 사용 중인지 확인하고 실패한다. 따라서 기존 Server process, Docker Compose project, 운영 환경을 종료하지 않는다. Harness가 직접 생성한 child process만 bounded `terminate`/`kill`로 종료하고, PostgreSQL에는 stop/reset 명령을 보내지 않는다.

## 검증 단계

1. owned Spring Boot process와 기존 PostgreSQL로 clean startup
2. Mock Robot 등록과 Agent registration/READY
3. Session → Block Revision → Simulation Pass → Execution
4. baseline Execution의 `QUEUED → ASSIGNED → RUNNING → COMPLETED`
5. 두 번째 Execution을 `RUNNING`에 고정
6. owned Server process 중지
7. Agent `DEGRADED`, `operationalReady=false`, polling 차단, 추가 dispatch 없음 확인
8. 동일 DB를 사용하는 Server process 재시작
9. 기존 credential로 reconnect 및 `FAILED` reconciliation
10. Robot release, `command replay=0`, Agent READY 확인
11. 같은 persisted Session/Block Version으로 post-recovery Execution 완료
12. final consistency audit 및 official Robot `UNAVAILABLE` cleanup

## Race 및 persistence

Server offline recovery scheduler와 Agent explicit recovery가 어느 쪽이 먼저 실행되더라도 Server의 lock/idempotency 계약이 최종 terminal state와 Robot release를 결정한다. Harness는 DB를 직접 수정하지 않고 public/admin HTTP와 Agent internal HTTP contract만 사용한다.

Server process restart만 수행하므로 Flyway가 기존 schema를 사용해야 한다. 재시작 전후 Execution ID, Robot ID, Session ID, Block Version이 유지되고, 기존 Session token으로 post-recovery 요청이 성공해야 한다.

## Cleanup 및 실패 해석

모든 fixture와 owned process는 `finally`에서 정리한다. cleanup failure는 primary rehearsal failure를 덮지 않는다. Server가 outage 상태로 실패하면 cleanup이 먼저 owned Server를 복구한 뒤 Robot을 official admin API로 `UNAVAILABLE` 처리한다. DB 직접 `UPDATE`/`DELETE`, heartbeat timeout을 기다리는 고정 sleep, hidden test endpoint는 사용하지 않는다.

## 수동 범위

systemd boot, OS reboot, 실제 deployment host 검증은 이 harness의 자동 범위가 아니다. 그 범위는 `docs/systemd-boot-recovery.md`의 disposable Linux 절차를 별도로 따른다.

## 안전 경계

이 rehearsal의 PASS는 Physical Readiness 또는 실제 Robot execution readiness를 의미하지 않는다. Physical Readiness는 계속 `BLOCKED`이며, hardware command path는 비활성 상태로 유지한다.
