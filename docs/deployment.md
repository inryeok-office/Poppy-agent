# Ubuntu systemd 운영

이 문서는 검증된 Ubuntu + Python venv 환경에서 Poppy-Agent를 systemd 서비스로
실행하는 방법을 설명한다. 서비스는 일반 사용자로 실행되며, runtime 설정과
인증 토큰은 repository 밖의 system-level EnvironmentFile에서 읽는다.

## 사전 조건

- Ubuntu/Linux와 systemd
- Python 3.11 및 Poppy-Agent 의존성을 설치한 venv
- Unitree 모드 사용 시 Unitree SDK2 Python과 CycloneDDS 설치
- `UNITREE_NETWORK_INTERFACE`에 사용할 OS 네트워크 인터페이스가 사전에 연결됨
- Poppy-Server에 접근 가능함

이 문서는 NetworkManager, IP 주소, GO2 설정을 변경하지 않는다. `enp3s0` 같은
인터페이스와 Unitree 네트워크는 OS에서 먼저 준비되어 있어야 한다.

## 경로와 사용자 확인

repository의 unit은 현재 검증된 운영 머신에 맞춰 다음 값을 사용한다.

```text
User=poppy
WorkingDirectory=/home/poppy/projects/Poppy-agent
ExecStart=/home/poppy/projects/Poppy-agent/.venv/bin/python -m poppy_agent.main
```

다른 사용자, repository 경로 또는 venv 경로를 사용하는 경우
`deploy/systemd/poppy-agent.service`의 `User`, `WorkingDirectory`, `ExecStart` 세
항목을 설치 전에 수정한다. `~`, `$HOME`, `source .venv/bin/activate`, shell
wrapper는 사용하지 않는다.

## EnvironmentFile 생성

repository root에서 example을 system-level 파일로 복사한다.

```bash
sudo mkdir -p /etc/poppy-agent
sudo cp deploy/systemd/poppy-agent.env.example /etc/poppy-agent/poppy-agent.env
sudo chown root:root /etc/poppy-agent/poppy-agent.env
sudo chmod 600 /etc/poppy-agent/poppy-agent.env
sudoedit /etc/poppy-agent/poppy-agent.env
```

`POPPY_ROBOT_ID`와 `POPPY_AGENT_TOKEN`을 실제 값으로 바꾸고, 나머지 운영 환경에
맞는 값을 확인한다. EnvironmentFile은 shell script가 아니므로 `$HOME`, `${HOME}` 또는
`${CYCLONEDDS_HOME}` 같은 expansion을 사용하지 않는다. CycloneDDS 경로도 실제
절대 경로를 직접 작성한다.

토큰이 포함된 실제 EnvironmentFile은 repository에 복사하거나 commit하지 않는다.
`root:root` 소유권과 `600` 권한을 유지하여 다른 사용자가 파일을 읽지 못하게 한다.

## 서비스 설치와 시작

```bash
sudo install -m 644 deploy/systemd/poppy-agent.service \
  /etc/systemd/system/poppy-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now poppy-agent
```

`enable`은 부팅 자동 시작을 설정하고, `--now`는 현재 즉시 시작한다. 시작을
나누어 실행하려면 다음을 사용한다.

```bash
sudo systemctl enable poppy-agent
sudo systemctl start poppy-agent
```

서비스는 `network-online.target` 이후 시작하도록 요청한다. Poppy-Server가 Agent보다
늦게 시작하여 registration이 실패하면 runtime은 non-zero로 종료하고, systemd가
5초 후 `Restart=on-failure` 정책으로 다시 시작한다.

## 상태와 로그

```bash
sudo systemctl status poppy-agent
sudo journalctl -u poppy-agent
sudo journalctl -u poppy-agent -f
sudo journalctl -u poppy-agent -b
```

Agent의 stdout/stderr는 journal로 전달된다. 로그나 점검 명령에서
`POPPY_AGENT_TOKEN`을 출력하지 않는다.

## 재시작과 중지

```bash
sudo systemctl restart poppy-agent
sudo systemctl stop poppy-agent
```

EnvironmentFile 값만 바꾼 경우에는 `restart`만 하면 된다. service unit을 바꾼
경우에는 먼저 daemon을 다시 읽힌다.

```bash
sudo systemctl daemon-reload
sudo systemctl restart poppy-agent
```

중지와 재시작 시 systemd는 기본적으로 SIGTERM을 보내며, Poppy-Agent의 기존
SIGTERM handler가 heartbeat loop를 끝내고 runtime shutdown을 수행한다. 별도 kill
script나 SIGKILL 기반 종료는 사용하지 않는다.

## 재부팅 검증 checklist

설치 후 다음 순서로 실제 운영 상태를 확인한다.

1. Ubuntu를 재부팅한다.
2. `enp3s0` 연결 상태를 확인한다.
3. `sudo systemctl status poppy-agent`로 서비스 상태를 확인한다.
4. `sudo journalctl -u poppy-agent -b`에서 현재 부팅 로그를 확인한다.
5. `Agent registered` 로그를 확인한다.
6. `Heartbeat loop started` 로그를 확인한다.
7. Poppy-Server에서 Robot이 `ONLINE`인지 확인한다.
8. `lastHeartbeatAt`이 heartbeat 주기에 맞춰 갱신되는지 확인한다.

이 절차에는 Robot movement 테스트가 포함되지 않는다.
