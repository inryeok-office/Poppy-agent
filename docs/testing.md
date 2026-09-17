# Testing

The local verification suite is intentionally small and deterministic:

```bash
python scripts/harness_check.py
ruff check .
ruff format --check .
mypy
pytest
```

Phase 2 tests cover configuration validation, Mock Robot initialization and state,
adapter capabilities, Agent startup, and graceful shutdown. Phase 3 tests use an
in-process HTTP transport to cover request/header mapping, response parsing, nullable
heartbeat fields, HTTP errors, timeout/connection failures, and malformed responses.
Tests must not require a physical robot, robot network, secret, or a running
Poppy-Server unless a later Issue explicitly defines a separately controlled
integration test. Unitree adapter tests use a fake SDK module and never initialize DDS.
Physical movement and posture commands are never test fixtures.

## Full Mock E2E

The cross-repository Server-Agent command pipeline is intentionally separate from
the local verification suite because it requires a running Poppy-Server and
PostgreSQL. Run it only against an ephemeral localhost environment with
`python scripts/full_mock_e2e.py`; see [`full-mock-e2e.md`](full-mock-e2e.md) for
the prerequisites, safety guard, fixture, and success criteria.

## Two-Robot / Two-Agent Concurrent Mock E2E

The isolated concurrency harness uses two real local Agent runtimes and the
ephemeral local Server/PostgreSQL environment. Start the documented local
Poppy-Server environment first, then run:

```bash
python scripts/two_agent_mock_e2e.py
```

The harness creates two independent mock Robots, registers two Agents, and
verifies runtime credential isolation, concurrent execution ownership,
cancellation isolation, interrupted-execution recovery, Robot release, and
post-terminal no-work polling. It uses HTTP/domain flows and never initializes
Unitree SDK, DDS, SportClient, or physical hardware. See
[`two-agent-mock-e2e.md`](two-agent-mock-e2e.md) for prerequisites and the
assertion scope.

## Stale Agent Fencing E2E

The stale-Agent harness verifies runtime credential rotation and fail-closed
handoff for an existing Robot. Run it only against the ephemeral localhost
Server/PostgreSQL environment:

```bash
python scripts/stale_agent_fencing_e2e.py
```

It verifies old credential rejection on heartbeat, polling, status, and
recovery endpoints; same-agent re-registration; active RUNNING recovery without
command replay; stale terminal-report protection; Robot release; and new work
after recovery. It uses Mock executors only. See
[`stale-agent-fencing.md`](stale-agent-fencing.md).

Each scenario retires its Robot fixture through the official admin Robot update
API (`operationalStatus=UNAVAILABLE`) in both success and failure cleanup paths.
The harness verifies the Robot is unoccupied with no current Execution before
the next scenario proceeds, so repeated runs do not depend on heartbeat
timeout or direct database mutation.

## Software-only Operational Recovery Rehearsal

The operational recovery rehearsal combines normal execution, an active
transport outage, authoritative interruption reconciliation, Agent runtime
replacement, stale credential fencing, operational snapshot checks, and final
Robot ownership cleanup in one persistent local scenario:

```bash
python scripts/operational_recovery_rehearsal.py
```

Run it only against the documented ephemeral localhost Server/PostgreSQL
environment. The harness uses a controllable client-side transport wrapper and
the official Robot admin lifecycle API; it does not modify the Server source or
database directly. It never replays an interrupted command. See
[`operational-recovery-rehearsal.md`](operational-recovery-rehearsal.md) for
the phase timeline, snapshot expectations, cleanup contract, and the boundary
between automated software rehearsal and manual Server/systemd restart checks.

## Command Safety Validation

`ExecutionSafetyValidator` is covered by local tests using only mock targets. The
tests verify target support preflight, robot binding, PRESET fail-closed behavior,
trace-only Mock PRESET behavior, and the existing STOP/lifecycle regressions. No
physical Robot or Unitree command API is initialized.
