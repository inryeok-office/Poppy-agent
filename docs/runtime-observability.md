# Runtime Observability Contract

## Scope

Poppy-Agent는 표준 Python `logging`으로 Agent 등록, runtime, execution,
cancellation, interrupted execution recovery, Server transport 상태를 구조화해 기록한다.
이 문서는 로그를 외부 backend로 전송하는 방법이 아니라, 운영자가 동일한 이벤트 이름과
context로 lifecycle을 추적하기 위한 계약이다.

## Event vocabulary

수명주기 이벤트는 다음 stable name을 사용한다.

- Agent: `agent_starting`, `agent_registered`, `runtime_ready`, `startup_failure`,
  `runtime_stopping`, `runtime_stopped`
- Execution: `execution_assigned`, `execution_started`, `execution_completed`,
  `execution_failed`, `execution_cancelled`
- Cancellation: `execution_cancellation_detected`, `execution_cancellation_requested`
- Recovery: `execution_recovery_checked`, `execution_recovery_no_active`,
  `execution_recovery_detected`, `execution_recovery_started`,
  `execution_recovery_completed`, `execution_recovery_failed`
- Transport: `server_request_retry`, `server_request_failed`, `server_response_invalid`

## Log levels

- `INFO`: startup/registration/ready/shutdown, assignment, execution terminal 상태,
  cancellation, recovery lifecycle
- `WARNING`: 재시도, Server가 취소를 보고한 상태, interrupted execution 발견
- `ERROR`: startup/recovery 실패, 재시도 소진, transport 실패, execution 실패
- `DEBUG`: heartbeat/no-work polling 같은 고빈도 정상 상태가 필요할 때만 사용

정상 heartbeat와 no-work polling은 기본적으로 INFO로 기록하지 않는다.

## Context fields

이벤트에 의미가 있는 경우에만 `agent_id`, `robot_id`, `execution_id`,
`execution_status`, `recovery_action`, `error_type`, `attempt`, `max_attempts`,
`protocol_version`, `method`, `path`, `status_code`를 사용한다.
timestamp, level, logger name은 formatter가 생성한다.

## Secret redaction

허용 목록에 없는 context는 버린다. Agent bootstrap token, runtime agent token,
`X-Agent-Token`, Authorization/Cookie, request header, request/response body,
`commandPayload`, 환경 변수 dump는 어떤 level에서도 기록하지 않는다.
예외도 raw message 대신 안전한 exception type만 기록한다.

## Execution, cancellation, and recovery

`execution_assigned`부터 `execution_started`와 terminal 이벤트까지를 기록한다.
Server가 `CANCELLED`를 반환한 사실과 cooperative cancellation 요청을 별도 이벤트로
기록하며, Program STOP이나 physical emergency stop으로 해석하지 않는다.

재시작 복구는 discovery, active execution 발견, reconciliation 시작/완료/실패를
기록한다. 복구 과정에서 command replay는 하지 않는다.

## Server transport failures

bounded retry가 발생하면 `server_request_retry`, timeout/connection failure가
종료되면 `server_request_failed`, 성공 응답 envelope가 잘못되면
`server_response_invalid`를 기록한다. 경로는 query를 제거한 path만 기록한다.

## Physical readiness boundary

이 logging 구현은 소프트웨어 lifecycle 관측을 개선할 뿐이다. Physical Readiness는
여전히 `BLOCKED`이며 real Unitree command client, production MotionProfile,
physical limit, PRESET 정책, emergency procedure, hardware validation 및 장비 담당자
승인을 충족시키지 않는다. Hardware validation status: **NOT TESTED ON HARDWARE**.

## Explicit non-goals

Metrics, tracing, OpenTelemetry, Prometheus, Grafana, ELK/Loki/Sentry, Poppy-Server
변경, Unitree GO2 연결, SportClient/DDS command, physical movement와 physical
emergency stop은 이 계약의 범위가 아니다.
