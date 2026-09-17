# Execution Recovery Contract

## Scope

This contract handles Agent restart after local execution state is lost. It is a
software lifecycle reconciliation path only. It never resumes or replays a command
program and never issues a physical stop.

## Server authority

Poppy-Server is the source of truth for Execution lifecycle and Robot ownership.
After registration, the Agent discovers the bound Robot's active execution through:

```text
GET /api/v1/internal/agents/{agentId}/robots/{robotId}/active-execution
```

If the result is active, the Agent calls:

```text
POST /api/v1/internal/agents/{agentId}/robots/{robotId}/active-execution/recover
```

The Server transaction changes `ASSIGNED` or `RUNNING` to `FAILED`, records the
terminal state, and releases the Robot. The recovery operation is idempotent; a
second call after release reports `NO_ACTIVE_EXECUTION`.

## Startup ordering

```text
Agent adapter start
    -> Agent registration / credential rotation
    -> active execution discovery
    -> optional Server reconciliation
    -> heartbeat and execution polling
```

Recovery is completed synchronously by `AgentServerRuntime.start()`. A discovery or
reconciliation transport failure aborts startup, so the Agent cannot begin polling
while recovery state is unknown.

## Crash windows

- `ASSIGNED` before `RUNNING`: recovery marks the assignment `FAILED`; it is not
  delivered again.
- `RUNNING` before or during a command: progress is unknown; no command is replayed.
- Local completion before the terminal report: Server still wins; an active Server
  state is reconciled as interrupted rather than replayed.
- Server `CANCELLED` or another terminal state: terminal lifecycle rules remain
  authoritative and are not overwritten by recovery.

## Cancellation versus crash

User/server cancellation is represented by `CANCELLED` and is propagated through the
cooperative cancellation token. An Agent restart is not a user cancellation; it is
reconciled as `FAILED` because the execution did not complete and progress cannot be
proven.

Program STOP, Execution Cancellation, Administrative Stop, and Physical Emergency
Stop remain distinct concepts. Recovery does not call a physical stop operation.

## Ownership and stale Agents

Registering an existing Agent name rotates its Server-issued credential. Recovery
requires the current authenticated Agent and its Robot binding, so a stale Agent
credential cannot recover or report through the new Agent contract. This is a
bounded handoff rule, not a distributed lease or physical-stop guarantee; a future
hardware enablement review must address any remaining stale-process risk.

## Current limitations

- No checkpoint, resume, or sequence acknowledgement exists.
- No local execution journal is required or used.
- No timeout value is invented for crash detection; the Server's existing OFFLINE
  recovery remains a separate scheduler policy.
- Recovery has not been tested on physical hardware.

## Local Mock verification

With a local Poppy-Server and PostgreSQL running, the restart contract can be
verified without a Robot:

```powershell
$env:POPPY_E2E_SERVER_URL = "http://localhost:8080"
$env:POPPY_E2E_AGENT_TOKEN = "local-recovery-e2e-token"
python scripts\execution_recovery_e2e.py
```

The scenario uses two in-process Mock Agent runtimes and real HTTP transport.
The first runtime reports `RUNNING` and is interrupted before a terminal report;
the second runtime discovers and reconciles the Server-owned execution. It
asserts no command replay, `FAILED` reconciliation, Robot release, and no
subsequent work.

The development Mock adapter advertises the command capability codes needed for
Server re-registration compatibility, but Server capability `VERIFIED` status
still remains an explicit fixture/admin decision and is not inferred by Agent
advertisement.

## Hardware boundary

All recovery tests use Mock/Fake software components. Unitree SDK commands,
SportClient, DDS command publishing, movement, and physical emergency stop are
outside this contract.
