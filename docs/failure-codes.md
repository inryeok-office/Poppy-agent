# 실행 실패 코드 (#101)

Agent 는 FAILED 실행마다 `ExecutionResult.failure_code` 와 구조화 로그 `execution_failed` 의
`failure_code` 필드에 아래 코드 중 하나를 남긴다. SDK 원문 오류·반환 코드·토큰은 코드와 메시지에 넣지 않는다.

| 코드 | 의미 | 발생 위치(현재 develop) |
|---|---|---|
| `SAFETY_REJECTED` | 안전 정책·guard 한도로 dispatch 전 거부 | `ExecutionSafetyValidator`, `OpenMotionGuard`/`TrialGuard` 한도 |
| `APPROVAL_EXPIRED` | 실제 동작 승인 시간 만료 | `OpenMotionGuard.admit` |
| `TELEMETRY_STALE` | 로봇 텔레메트리가 신선하지 않아 거부 | `OpenMotionGuard`/`TrialGuard` |
| `POSTURE_UNKNOWN` | 자세 불명으로 거부 | #110(#98) 머지 후 연결 |
| `SDK_REJECTED` | SDK 가 명령을 거절(0 이 아닌 결과) | `UnitreeSdkCommandClient._call_operation`, backend 결과 검사 |
| `TIMEOUT` | SDK `Move` 호출이 제한 시간 이상 막힘 | `execute_motion_with_cancellation` |
| `NOT_MOVED` | 폐루프에서 미이동 판정 | #97 폐루프 머지 후 연결 |
| `EXECUTION_ERROR` | 위에 해당하지 않는 실패(전송 예외, StopMove 미확인 등) | 기본값 |

코드는 예외가 만들어지는 곳에서 `failure_code` 로 붙이고(`CodedError`), executor 는 원인 체인에서 첫 코드를
찾는다(`failure_code_of`). 코드가 없으면 위치별 기본값(guard 는 `SAFETY_REJECTED`, 실행 중은 `EXECUTION_ERROR`)이다.

## Server 보고 (미연결)

Server 계약(Poppy-Server#134 `failureCode`, `failureMessage`)이 확정되지 않아 아직 보고하지 않는다.
CLAUDE.md 에 따라 계약을 추측해 payload 를 바꾸지 않는다. 제안:

- `PATCH` 실행 상태 보고 payload 에 `failureCode`(위 값, FAILED 일 때만)를 선택 필드로 추가.
- `failureMessage` 는 Server 가 코드로 만든 고정 안내문을 쓴다(Agent 의 `failure_reason` 원문은 보내지 않음).
- 이전 Server 와의 호환: 필드가 없으면 기존 동작. 재시도·중복 보고 시 같은 코드를 다시 보낸다.
