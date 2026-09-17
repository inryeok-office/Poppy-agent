# Agent Operational Health / Readiness

## Scope

This contract exposes the software runtime state of Poppy-Agent as a local,
machine-readable snapshot. It answers whether the process is operationally
cooperating with Poppy-Server; it does not authorize physical Robot execution.

Physical Execution Readiness remains a separate contract and stays `BLOCKED`.
Hardware validation status: **NOT TESTED ON HARDWARE**.

## Liveness, readiness, and availability

- `liveness` describes whether the local runtime has not reached `STOPPED` or
  `FAILED`.
- `operationalReady` is true only after registration and startup recovery have
  completed, Server connectivity is `CONNECTED`, and the runtime lifecycle is
  `READY`.
- `acceptingNewExecution` is stricter: operational readiness, enabled execution
  polling, and no active execution are all required. An active execution does
  not make the Agent unhealthy; it only makes it unavailable for another one.
- `ROBOT_MODE=unitree` remains telemetry/heartbeat-only, so it reports operational
  state independently while `acceptingNewExecution` remains false.

## Snapshot schema

When `POPPY_RUNTIME_STATUS_PATH` is configured, the Agent publishes JSON with:

`schemaVersion`, `observedAt`, `lifecycleState`, `connectivityState`, `liveness`,
`registered`, `agentId`, `robotId`, `activeExecutionId`, `recoveryComplete`,
`operationalReady`, `acceptingNewExecution`, `readinessReasons`,
`lastServerSuccessAt`, and `lastHeartbeatSuccessAt`.

Lifecycle values are `STARTING`, `READY`, `DEGRADED`, `STOPPING`, `STOPPED`, and
`FAILED`. Connectivity values are `CONNECTED` and `DEGRADED`. Readiness reasons
are stable values such as `NOT_REGISTERED`, `STARTUP_RECOVERY_PENDING`,
`SERVER_CONNECTIVITY_DEGRADED`, `AUTHENTICATION_FAILED`, `RUNTIME_STOPPING`,
and `RUNTIME_FAILED`.

All timestamps are timezone-aware UTC ISO-8601 values. Success timestamps change
only after a successful Server interaction; failures never refresh them.

## Status file and systemd

Publication writes a temporary file in the destination directory, flushes it,
and atomically replaces the configured path. Readers therefore never observe a
partially written JSON document. A publication failure is logged as a structured
error and does not change execution or Server lifecycle semantics.

The systemd unit provisions `RuntimeDirectory=poppy-agent`; the example
environment sets `/run/poppy-agent/status.json`. Graceful shutdown publishes the
terminal state and removes the file. An absent file means no current graceful
runtime status is available; operators should also inspect `observedAt` after an
unexpected process failure.

## Secret safety

The snapshot never contains bootstrap/runtime tokens, headers, credentials,
command payloads, responses, or environment dumps. UUID identities and execution
IDs are included only as operational identifiers.

## Physical readiness boundary

An operationally ready Agent is not physically ready. The existing Physical
Readiness Contract continues to require an approved production motion profile,
physical limits, PRESET policy, emergency procedure, hardware validation, and
equipment-owner approval. This change adds no hardware command or safety value.

## Explicit non-goals

This is not an HTTP health listener, metrics endpoint, Prometheus/Grafana,
OpenTelemetry, external log shipping, Unitree command integration, or a physical
GO2 test.
