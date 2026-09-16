# Server-Agent Full Mock Command E2E

이 harness는 실제 Unitree GO2 없이 실행 중인 Poppy-Server와 Poppy-agent를 실제
HTTP로 연결하여 Session, Block Revision, Simulation Pass, Execution Request,
capability-aware allocation, Agent delivery, typed Mock command trace, terminal
status, Robot release까지 검증한다.

## 안전 범위

- harness는 `ROBOT_MODE=mock`에 해당하는 Agent production class만 생성한다.
- `POPPY_E2E_SERVER_URL`은 `http://localhost`, `http://127.0.0.1`, `http://[::1]`만 허용한다.
- Unitree SDK, SportClient, DDS, motor, joint, torque, 실제 movement와 hardware를 사용하지 않는다.
- `WAIT`는 Agent Mock executor에서 실제 sleep하지 않는다. harness의 sleep은 HTTP polling 간격뿐이다.
- 매 실행마다 새로운 Robot UUID, Agent name, Session을 생성한다. Server에 delete API가 없으므로
  반복 실행 후 fixture가 남을 수 있다.

## 사전 조건

- Python 3.11 및 Agent 개발 의존성 설치
- Java 25, Gradle wrapper 및 Docker Desktop
- Poppy-Server `develop` checkout
- PostgreSQL 16과 Server가 local profile로 실행 중
- Server bootstrap `POPPY_AGENT_TOKEN`과 동일한 `POPPY_E2E_AGENT_TOKEN`

Server repository에서 PostgreSQL과 애플리케이션을 시작한다.

```powershell
cd ..\Poppy-Server
$env:POPPY_AGENT_TOKEN = "local-e2e-token"
docker compose up --build
```

기존 local Server를 이미 실행 중이라면 Server 시작을 반복하지 않고,
애플리케이션의 bootstrap token만 `POPPY_E2E_AGENT_TOKEN`과 일치시키면 된다.
Docker compose의 기본 애플리케이션 주소는 `http://localhost:8080`이다.

## 실행

Agent repository root에서 실행한다.

```powershell
cd ..\Poppy-agent
$env:POPPY_E2E_SERVER_URL = "http://localhost:8080"
$env:POPPY_E2E_AGENT_TOKEN = "local-e2e-token"
python scripts\full_mock_e2e.py
```

환경 변수:

- `POPPY_E2E_SERVER_URL`: 필수 local HTTP URL
- `POPPY_E2E_AGENT_TOKEN`: 필수 Server bootstrap token
- `POPPY_E2E_TIMEOUT_SECONDS`: allocation/status bounded timeout, 기본 30초, 최대 120초
- `POPPY_E2E_POLL_INTERVAL_SECONDS`: polling 간격, 기본 0.2초
- `POPPY_E2E_HTTP_TIMEOUT_SECONDS`: 개별 HTTP timeout, 기본 5초

Server는 기본 queue dispatcher 주기인 1초 안에 Execution을 배정한다. harness는
직접 allocation service를 호출하지 않고 HTTP status를 bounded polling한다.

## 검증 시나리오

fixture Block Program은 다음 순서다.

`START → WAIT(1.5s) → MOVE_FORWARD(1.25m) → TURN_LEFT(90°) → SIT → STAND → STOP → WAIT(dummy) → END`

Execution Request 뒤에 더 최신 Block Revision을 하나 추가하여, Agent delivery가
첫 번째 revision의 immutable compiled command snapshot을 유지하는지 확인한다.
`WAIT`, `MOVE`, `TURN`, `POSTURE`, `STOP`에 필요한 command capability는 Robot admin
PATCH로 명시적인 `VERIFIED` 상태를 설정한다. Agent가 광고한 capability code를
자동으로 VERIFIED 처리하지 않는다.

성공 기준:

- Session, Block Revision, Simulation Pass, Execution Request 성공
- 초기 `QUEUED`, 이후 `ASSIGNED`, Agent report `RUNNING`, 최종 `COMPLETED`
- delivery `commandPayload`의 strict parse 성공
- Mock trace가 `WAIT, MOVE, TURN, POSTURE, POSTURE, STOP` 순서
- sourceBlockId와 typed parameter 보존
- STOP 뒤 dummy WAIT 미실행
- Robot `occupied=false`, `currentExecutionId=null`
- Agent의 완료 후 polling이 no-work 반환

## 실패와 정리

네트워크, 인증, validation, allocation 또는 terminal status 오류는 실패로 출력되며
token은 redaction된다. Server에 fixture 삭제 API가 없으므로 개인의 ephemeral Docker
PostgreSQL을 사용하고 production URL을 절대 입력하지 않는다. Server를 중지하려면
별도 터미널에서 `docker compose down`을 사용한다. 영속 volume을 포함한 삭제는
이 harness가 수행하지 않는다.
