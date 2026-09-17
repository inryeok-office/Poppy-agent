# Stale Agent Fencing and Ownership Contract

## Scope

This contract covers duplicate Agent processes for the same logical Agent and
Robot. It verifies the existing Server credential and principal-binding rules
without enabling physical Robot execution.

## Existing Server contract

Registration with an existing `agentName` reuses the Server `agentId` and
rotates the stored credential digest. The newly issued runtime credential is
valid; the previous credential is immediately invalid. Every internal Agent
endpoint authenticates the credential and checks that the authenticated
principal matches the `{agentId}` path.

The Robot binding remains tied to the logical Agent. A different Agent cannot
bind the same Robot; the Server rejects that registration. This is credential
and principal fencing, not a distributed lease implementation.

## Idle duplicate registration

After a new registration for the same logical Agent, the old runtime must not
be able to call:

- heartbeat;
- next-execution polling;
- execution status read or report; or
- active-execution discovery or recovery.

The new credential may heartbeat and poll. Raw credentials are never printed or
included in test output.

## Active execution handoff

If the old runtime is in `RUNNING` and a new runtime registers, the new runtime
performs the existing startup recovery contract:

```text
new registration
    -> active execution discovery
    -> interrupted execution reconciliation
    -> FAILED terminal state
    -> Robot release
```

The old runtime does not replay or resume the command program. Its next
authoritative status check receives authentication failure, cooperatively
interrupts the Mock executor, and cannot submit a terminal report with the old
credential. A replacement Agent can then receive new work.

## Race protection

An old heartbeat or terminal report after rotation is rejected before it can
overwrite the new Agent's Robot state or the recovered terminal Execution
state. Recovery uses the Server's existing transaction and remains
authoritative; no local Agent memory is used as proof of progress.

## Authentication failure policy

401/403 authentication or principal failures are not transient reconnects and
do not trigger automatic re-registration. This prevents credential rotation
ping-pong between duplicate processes. The Agent runtime remains fail-closed;
it does not translate stale credential loss into user `CANCELLED` or a physical
stop.

## Verification

Run against local Poppy-Server and PostgreSQL:

```powershell
$env:POPPY_E2E_SERVER_URL = "http://localhost:8080"
$env:POPPY_E2E_AGENT_TOKEN = "local-stale-agent-e2e-token"
python scripts\stale_agent_fencing_e2e.py
```

The scenario is software-only and does not use GO2, Unitree SDK commands,
SportClient, DDS command publishing, physical movement, or physical emergency
stop.

Hardware validation status: **NOT TESTED ON HARDWARE**.
