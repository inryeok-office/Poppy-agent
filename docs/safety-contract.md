# Poppy Command Execution Safety Contract

## Scope

This contract defines the software safety boundary for command execution before a
physical robot target is enabled. It applies to the Agent-side transition:

```text
HighLevelCommandProgram
    -> ExecutionSafetyValidator
    -> ExecutionTarget
```

This document does not authorize or implement Unitree control, physical movement,
or a hardware emergency stop.

## Trust Boundaries

```text
Web Block JSON
    -> Poppy-Server validation/compiler
    -> immutable Command Protocol snapshot
    -> Agent strict parser
    -> typed HighLevelCommandProgram
    -> Agent safety validation
    -> execution target
    -> physical robot (disabled in this phase)
```

- Web input is not sent directly to the Agent.
- Poppy-Server owns Block Program validation, compilation, immutable snapshots, and
  VERIFIED capability-aware allocation.
- The Agent owns strict parsing, execution identity/lifecycle checks, and whether
  its selected execution target supports the typed command.
- An execution target must not silently ignore, replace, or downgrade an unsupported
  command.

## Safety Invariants

1. Only a strict-parser-produced typed `HighLevelCommandProgram` may enter the
   execution boundary.
2. An unsupported protocol version or a program/task version mismatch is rejected
   before target dispatch.
3. The delivered `robotId` must match the Agent's bound robot identity. The runtime
   performs this delivery check, and the validator can enforce the same binding when
   configured.
4. Only an `ASSIGNED` delivery is eligible for execution, and one runtime tracks at
   most one active execution.
5. Command sequences must remain contiguous and are preflighted in full before the
   first target dispatch.
6. Unknown command types, malformed typed parameters, and unsupported target
   commands fail closed.
7. A safety failure cannot result in `COMPLETED` and does not dispatch any command.
8. Execution exceptions are not converted into success.
9. Network or status-report failures are not converted into command success.
10. Credentials and session/Agent tokens are not logged.
11. If no real execution implementation is available, the Agent does not silently
    fall back to Mock execution.

## STOP Semantics

These are separate concepts:

- **Program STOP**: a typed protocol command. The target records/handles STOP and
  the executor ends the current program successfully; later program commands are
  not dispatched. This is not an emergency stop.
- **Execution Cancellation**: a lifecycle operation that prevents or cancels an
  execution. It is not implemented by the Agent safety layer in this change.
- **Administrative Stop**: a future administrator/API request to stop an execution.
  No Admin API is added here.
- **Physical Emergency Stop**: a hardware/operator safety mechanism. It is outside
  this Agent contract and is not implemented or simulated here.

## Fail-closed Policy

`ExecutionSafetyValidator` preflights every command against the selected
`ExecutionTarget` before the executor can call `dispatch`. If target support is
unknown, unavailable, or returns anything other than explicit support, validation
fails. The executor returns a deterministic `FAILED` result with the validation
reason and leaves the target trace unchanged.

The validator has no distance, angle, speed, battery, obstacle, acceleration,
torque, joint, or latency limits. Such values are not established by this project
and remain unresolved.

## PRESET Policy

`PRESET` remains available in the Mock trace-only target so protocol and pipeline
behavior can be tested. A non-Mock/physical-like target must provide an explicit
allow-list through `CommandSafetyPolicy.preset_allowlist`. With no allow-list, or
with a code absent from it, PRESET fails closed. No preset names or Unitree mapping
are defined by this project.

## Capability Responsibilities

Poppy-Server decides whether a Robot is eligible for allocation using
`requiredCapabilities` and explicitly `VERIFIED` capabilities. The Agent does not
replace that matcher or treat advertised capability codes as verified.

After delivery, the Agent safety layer checks the selected execution target's
actual command support. These are complementary checks: Server allocation selects
an eligible Robot, while Agent execution refuses a command that its local target
cannot explicitly support.

## Connection and Runtime Failure

The Agent remains fail-closed when registration, polling, status reporting, or
execution target operations fail. A failed safety validation or executor failure
must be reported as `FAILED` through the existing runtime contract where reporting
is available. It must never be reported as `COMPLETED`.

## Physical Safety Limits

The following values are **TBD** and must not be guessed in production code:

- maximum MOVE distance or speed
- maximum TURN angle or speed
- posture safety range
- battery threshold
- obstacle distance
- acceleration, torque, or joint range
- emergency-stop latency
- PRESET allow-list

## Hardware Enablement Gate

Physical command execution remains disabled until all of the following are complete:

- Full Mock E2E passes on the supported Server-Agent contract.
- This Safety Contract and its validation tests are reviewed and merged.
- An execution-target abstraction and hardware-specific mapping are reviewed.
- Physical safety limits and the PRESET allow-list are explicitly decided from
  authoritative product/equipment sources.
- A controlled bench-validation plan, rollback/stop procedure, and observability
  review are approved by the responsible equipment owner.
- Unitree SDK integration is tested first with a fake SDK boundary and without
  enabling physical control in the Agent by default.

No condition in this document is a substitute for an operator or hardware
emergency-stop procedure.
