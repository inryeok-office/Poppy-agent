# systemd / Boot Recovery Contract

## Scope

이 문서는 Poppy-agent의 Ubuntu systemd 배포 계약과 software-only recovery 검증 범위를
정의한다. 실제 GO2, Unitree SDK, SportClient, DDS command publisher, physical movement,
physical emergency stop은 포함하지 않는다.

Physical Readiness와 operational process recovery는 별개다. Mock mode에서 systemd rehearsal이
통과해도 Physical Readiness는 계속 `BLOCKED`다.

## Service Layout

기본 unit은 [`deploy/systemd/poppy-agent.service`](../deploy/systemd/poppy-agent.service)다.

- `Wants/After=network-online.target`: network target 이후 시작을 요청하지만 Poppy-Server
  availability까지 보장하지 않는다.
- `Type=simple`: `poppy_agent.main` process가 서비스 process다.
- `User=poppy`: 전용 운영 user를 사용한다.
- `WorkingDirectory=/home/poppy/projects/Poppy-agent`
- `EnvironmentFile=/etc/poppy-agent/poppy-agent.env`
- `RuntimeDirectory=poppy-agent`, `RuntimeDirectoryMode=0750`
- `Restart=on-failure`, `RestartSec=5`
- `TimeoutStopSec=15`
- stdout/stderr는 journald로 전달된다.

## Installation Assumptions

운영 설치에는 다음 구조가 필요하다.

```text
/home/poppy/projects/Poppy-agent
/home/poppy/projects/Poppy-agent/.venv/bin/python
/etc/poppy-agent/poppy-agent.env
/run/poppy-agent/status.json
```

`poppy-agent.env`는 root가 소유하고 Agent service user만 읽을 수 있어야 한다. 실제 token은
이 문서나 repository에 기록하지 않는다. 예시 값은
[`poppy-agent.env.example`](../deploy/systemd/poppy-agent.env.example)을 사용한다.

## Installation Runbook (software contract)

실제 장비 설정 없이 배포 구조만 검증하는 순서는 다음과 같다.

```bash
python3 -m venv /home/poppy/projects/Poppy-agent/.venv
/home/poppy/projects/Poppy-agent/.venv/bin/pip install /home/poppy/projects/Poppy-agent
install -d -o root -g poppy -m 0750 /etc/poppy-agent
install -o root -g poppy -m 0640 deploy/systemd/poppy-agent.env /etc/poppy-agent/poppy-agent.env
install -o root -g root -m 0644 deploy/systemd/poppy-agent.service /etc/systemd/system/poppy-agent.service
systemd-analyze verify /etc/systemd/system/poppy-agent.service
systemctl daemon-reload
systemctl enable poppy-agent.service
systemctl start poppy-agent.service
systemctl status poppy-agent.service
```

실제 운영 환경에서는 env의 `ROBOT_MODE`, Server URL, Robot identity, credential을 담당자가
확정해야 한다. 이 runbook은 physical execution enablement 절차가 아니다.

## RuntimeDirectory and Status Snapshot

systemd가 service start 시 `/run/poppy-agent`를 만들고 service user가 status snapshot을
작성한다. Agent는 atomic replace로 JSON을 갱신한다. 정상 stop에서는 status file과 runtime
directory가 정리되어 stale `READY` 파일이 남지 않아야 한다. 비정상 process kill 뒤에는
operator가 `observedAt`와 systemd state를 함께 확인해야 한다.

## Boot and Server-Unavailable Startup

`network-online.target`은 Server application/DB health를 보장하지 않는다. 시작 시 Server가
unavailable하면 main은 non-zero로 종료하고 systemd의 `Restart=on-failure`/`RestartSec=5`에
따라 다시 시도한다. Server가 복구되면 다음 process가 registration과 startup recovery를
수행하고 `READY/CONNECTED` snapshot으로 전환한다.

현재 unit은 영구 configuration 오류도 동일한 restart policy를 사용한다. 이로 인한 retry는
5초 cadence로 제한되어 hot loop는 아니지만, 별도의 operator diagnosis가 필요하다. 이번
작업에서는 서버 지연 복구를 막을 수 있는 임의의 `StartLimit*`나 새로운 exit-code taxonomy를
추가하지 않았다.

## Runtime Server Outage

서비스가 살아 있는 동안 Server가 내려가면 process를 재시작하지 않고 기존 runtime contract를
사용한다.

```text
CONNECTED → DEGRADED → reconnect → CONNECTED
```

새 Execution polling은 연결이 확인될 때까지 차단된다. active Execution은 blind continuation
또는 command replay 없이 cooperative interruption과 authoritative reconciliation을 사용한다.

## Agent Process Crash and Active Execution Recovery

systemd가 process를 재시작하면 같은 logical Agent registration이 credential을 rotate한다.
기존 active Execution은 startup recovery에서 발견하고 기존 Server contract로 deterministic
terminal reconciliation한다. progress 추측과 command replay는 금지한다. OLD credential은
heartbeat, polling, status report, recovery 요청에 사용할 수 없다.

## Graceful Restart and Shutdown

`systemctl restart`는 SIGTERM을 보내고 Agent signal handler가 stop event를 설정한다.
run loop가 종료된 뒤 `runtime.shutdown()`이 adapter와 status snapshot lifecycle을 정리한다.
`TimeoutStopSec=15`는 software-only rehearsal에서 충분한지 확인한다. physical emergency stop
의 의미를 systemd stop에 부여하지 않는다.

## journald

```bash
journalctl -u poppy-agent.service --no-pager -o cat
```

startup, registration, readiness, degraded/reconnect, recovery, shutdown event를 확인할 수
있어야 한다. bootstrap/runtime token, Authorization header, command payload, session token,
raw HTTP body는 journal에 남기지 않는다.

## Rehearsal Environment

실제 systemd 검증은 disposable Ubuntu/WSL systemd 환경에서만 수행한다. harness는 다음 guard를
요구한다.

- Linux systemd PID 1이 `running` 또는 `degraded`
- root 실행
- `POPPY_SYSTEMD_REHEARSAL=1`
- localhost HTTP Server와 test bootstrap token
- explicit Linux Python executable
- Mock mode만 허용

실행 예시는 다음과 같다.

```bash
POPPY_SYSTEMD_REHEARSAL=1 \
POPPY_E2E_SERVER_URL=http://localhost:8080 \
POPPY_E2E_AGENT_TOKEN='<local-test-token>' \
POPPY_SYSTEMD_REHEARSAL_PYTHON=/tmp/poppy-agent-systemd-venv/bin/python \
python3 scripts/systemd_recovery_rehearsal.py
```

Harness는 `/run/systemd/system/poppy-agent-rehearsal.service`라는 임시 test unit만 만들고,
production service를 직접 start/stop하지 않는다. test unit은 production unit에서 lifecycle
directive를 재사용하고, 종료 시 unit/env/runtime fixture와 test user를 제거한다. Docker
`poppy-app` 중지는 localhost test Server outage phase에서만 사용하며 DB volume은 삭제하지 않는다.

## Automated and Manual Checks

자동 rehearsal은 unit static contract, clean start, Server-unavailable startup retry, runtime
Server outage/reconnect, process crash와 active Execution recovery, graceful restart/stop,
RuntimeDirectory, status snapshot, journald secret safety를 확인한다.

실제 WSL/VM reboot는 사용자 개발 환경이나 운영 서버에서 자동 수행하지 않는다. `enable` link와
boot target 계약은 정적으로 확인하며, disposable VM의 실제 reboot는 별도 수동 check로 남긴다.

## Known Limitations

현재 `Restart=on-failure`는 permanent configuration error도 retry한다. 이를 production에서
별도로 차단하려면 restart budget과 operator remediation 정책을 먼저 결정해야 한다. Server와
Agent의 전체 계약 감사에서 후속 검토한다.

## Safety Boundary

이 계약과 rehearsal은 process supervision과 software lifecycle만 검증한다. 실제 Robot 연결,
Unitree command, production MotionProfile, physical limits, PRESET policy, emergency procedure,
hardware validation은 수행하거나 변경하지 않는다.
