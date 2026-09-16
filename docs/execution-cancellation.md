# Execution Cancellation Contract

## Scope

This document defines software-level cancellation propagation between
Poppy-Server and Poppy-Agent. It does not implement Robot control, a Unitree
command, or a physical emergency stop.

## Authority and HTTP contract

Poppy-Server is the source of truth for execution lifecycle state. The user
cancel endpoint may transition QUEUED, ASSIGNED, or RUNNING to terminal
CANCELLED and releases an assigned Robot. The Agent uses its authenticated
internal status endpoint:

GET /api/v1/internal/agents/{agentId}/executions/{executionId}/status?robotId={robotId}

The existing status report endpoint accepts CANCELLED as a terminal report.
Server row locking and terminal transition rules prevent stale Agent
COMPLETED or FAILED reports from overwriting CANCELLED.

## Agent behavior

An ExecutionCancellationToken is created for each active execution. The
runtime polls authoritative Server state while the executor runs and sets the
token when Server reports CANCELLED. Executors observe it cooperatively at
execution start, command boundaries, and interruptible waits. Threads are not
force-killed.

The Agent reports CANCELLED, clears active_execution_id, and does not treat
cancellation as success or failure. If the Agent receives a stale assignment
whose RUNNING transition is rejected because Server already cancelled it, it
does not invoke the executor.

Cancellation status transport failure is fail-closed: the Agent requests local
cooperative cancellation and does not convert the uncertain execution into
COMPLETED.

## Cancellation boundaries

- before RUNNING is reported and before the first dispatch
- before each command dispatch
- after each command and before the next command
- during WAIT or a future interruptible motion wait when a cancellable sleeper
  is supplied

## Distinct stop concepts

- Program STOP is a typed command that ends the current program after its own
  trace event. It is not a lifecycle cancellation.
- Execution Cancellation is an external lifecycle request represented by
  CANCELLED.
- Administrative Stop is a future administrative operation and is not added
  here.
- Physical Emergency Stop belongs to hardware/operator responsibility and is
  not implemented or simulated.

## Race semantics

Server wins lifecycle races. If cancellation commits first, later Agent
COMPLETED/FAILED reports are rejected or treated as terminal replays and cannot
overwrite CANCELLED. If a terminal Agent report commits first, the Server
transition makes the execution terminal and a later user cancellation is
rejected. The Agent performs a final status check where the transport supports
it, but this check is not a replacement for Server transaction authority.

## Hardware boundary

Cancellation stops software dispatch only. It does not call StopMove,
SportClient, DDS, or any other Unitree operation, and it does not claim that a
physical Robot has stopped. Physical execution remains disabled.
