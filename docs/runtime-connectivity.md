# Runtime Connectivity Contract

## Scope

This contract covers transient communication failures between Poppy-Agent and
Poppy-Server. It is a software lifecycle contract and does not enable or control
physical Unitree hardware.

Poppy-Server remains the source of truth for execution lifecycle and Robot
ownership. Agent memory is never treated as proof that an execution completed.

## Failure classification

- Transport failures such as timeouts, connection refusal, and connection reset
  are transient candidates.
- HTTP 5xx responses are retried by the runtime as temporary Server failures.
- HTTP 401/403 responses are authentication or binding failures. They are not
  treated as transient outages and do not trigger an unbounded re-registration
  loop.
- Malformed successful responses, identity mismatches, and unsupported lifecycle
  values are contract failures. They fail closed instead of being retried as if
  the network were unavailable.

The HTTP client owns short, bounded request retries. The runtime owns the longer
degraded/reconnect state and does not add an unbounded busy loop.

## Connectivity state

The runtime exposes two states:

- `CONNECTED`: heartbeat and execution polling are allowed.
- `DEGRADED`: Server state cannot currently be confirmed. New execution polling
  is blocked.

An idle Agent may remain alive while it reconnects. A successful heartbeat returns
the runtime to `CONNECTED` and resets the reconnect delay.

## Reconnect policy

Reconnect uses positive, finite, bounded exponential backoff configured by:

- `POPPY_SERVER_RECONNECT_INITIAL_DELAY_SECONDS`
- `POPPY_SERVER_RECONNECT_MAX_DELAY_SECONDS`

The defaults are transport pacing defaults, not Robot safety limits or offline
timeouts. Waiting uses the runtime stop event, so SIGINT/SIGTERM interrupts a
backoff immediately.

## Idle connectivity loss

While `DEGRADED`, the Agent does not call the next-execution endpoint. It resumes
polling only after a successful heartbeat confirms Server connectivity again.

## Active execution connectivity loss

If an execution is active and Server communication becomes unavailable, the Agent
requests cooperative cancellation from its local executor. It does not force-kill
threads and does not translate a network interruption into user `CANCELLED`.

When connectivity returns, the Agent queries/reuses the existing active-execution
recovery contract. The Server decides whether the execution is already terminal or
must be reconciled as interrupted. Robot release follows the Server lifecycle path.

There is no command replay, sequence guessing, remaining-distance calculation, or
resume operation because execution progress is unknown.

## Ambiguous HTTP results

If a status or recovery POST response is lost, the Agent does not blindly repeat a
command or assume that the Server did not commit the request. It restores
connectivity and reconciles against the authoritative Server state before polling
new work.

## Authentication and contract failures

Authentication/binding failures are surfaced as non-recoverable runtime failures;
credential rotation is a separate explicit registration contract. Contract failures
are surfaced rather than hidden by reconnect retries. This prevents stale Agents
from competing through credential ping-pong.

## Shutdown

Process shutdown is distinct from connectivity degradation. A shutdown request
sets the stop event and ends reconnect waits promptly. It does not issue a physical
stop command.

## Structured events

Connectivity transitions use these stable events when applicable:

- `server_connectivity_lost`
- `server_connectivity_restored`
- `runtime_degraded`
- `runtime_resumed`
- `execution_interrupted_by_transport`
- `execution_reconciliation_started`
- `execution_reconciliation_completed`
- `execution_reconciliation_failed`
- `authentication_failure`

Logs do not contain tokens, headers, command payloads, or raw HTTP bodies.

## Explicit non-goals

This contract does not implement real Unitree SDK commands, SportClient, DDS
command publishing, physical movement, physical emergency stop, network interface
configuration, production motion limits, or external monitoring backends.

Hardware validation status: **NOT TESTED ON HARDWARE**.
