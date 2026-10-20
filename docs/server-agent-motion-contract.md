# Server–Agent physical motion contract

## Current canonical protocol

The Server target's protocol version 1 compiles block commands into `MOVE`
with `distanceMeters` and `TURN` with `angleDegrees`.  It has no duration or
velocity field.  The Agent preserves those units in `MotionPlan`; it does not
translate them into a Unitree `Move(vx, vy, vyaw)` call.

The Unitree call is velocity-shaped, while the current Poppy protocol is
distance/angle-shaped.  Without reviewed sign conventions, a duration policy,
and position or heading completion feedback, dispatch acknowledgement cannot
mean that a requested distance or angle was physically reached.

## Decision

No existing command mapping is changed by this work.  `MOVE` and `TURN`
remain unavailable to a physical executor until a reviewed, versioned protocol
extension is approved.  A safe future choice is a new protocol version that
has explicit bounded velocity and duration fields.  It must retain version 1
parsing for existing projects and simulators rather than reinterpreting stored
distance or angle values.

`STOP` remains program control, not a hardware emergency stop.  A timed motion
would require an explicit duration boundary followed by best-effort `StopMove`.
`StopMove` transport acknowledgement is distinct from a physical-stop
guarantee.

## Capability evidence

The Server has administrator-owned `COMMAND_MOVE` and `COMMAND_TURN`
capabilities.  A capability starts `UNVERIFIED`; Agent registration adds only
new advertised codes and heartbeat does not overwrite an administrator's
status.  Execution allocation already requires every command capability to be
`VERIFIED`.

This change adds the read-only, runtime-token endpoint:

```text
GET /api/v1/internal/agents/{agentId}/robots/{robotId}/capabilities
```

The existing Agent authentication interceptor verifies that the token resolves
to `{agentId}`.  The endpoint separately verifies that `{robotId}` is bound to
that Agent.  It returns only capability code and current status.  It does not
grant approval, expose administrator data, or add a database migration.

`TELEMETRY` verification is independent of `COMMAND_MOVE` and `COMMAND_TURN`.
Neither is a substitute for a reviewed motion profile, hardware validation, or
an operator emergency procedure.

## Remaining blockers

- approved production profile and numeric limits;
- versioned motion DTO plus compiler, simulator, and frontend alignment;
- local Agent capability evidence refresh/cache lifecycle before physical
  executor creation;
- bounded vendor-call isolation.  A Python timeout cannot forcibly terminate a
  blocking native SDK call in its worker thread;
- hardware validation and formal emergency procedure.
