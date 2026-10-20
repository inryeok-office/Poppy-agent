# Motion protocol v2 cross-repository plan

## Scope and compatibility

Protocol v1 remains immutable: stored projects compile `MOVE(distanceMeters)`
and `TURN(angleDegrees)`. Agent physical execution must reject v1 movement
until a reviewed compatibility policy exists; it must never reinterpret v1
values as velocity commands.

Protocol v2 should add explicit, bounded velocity and duration parameters:

- `linearVelocityMetersPerSecond` for forward/backward movement;
- `angularVelocityDegreesPerSecond` for yaw, retaining the existing Poppy
  degree convention. A future radians API requires a new field/version, not
  an implicit conversion;
- `durationSeconds`, measured with a monotonic clock.

Lateral velocity is excluded until a reviewed block, simulator model, and
Unitree sign convention exist. Direction is represented by a signed velocity
with a canonical documented sign table, rather than a second ambiguous field.

## Required changes

1. Server command DTO/parser/serializer accept protocol version 2 while v1
   stays readable.
2. Block schema and compiler emit v2 only for an explicitly selected new block
   version. Existing stored revisions remain v1.
3. Simulator integrates velocity over duration and labels the result as an
   open-loop estimate, not verified position or heading.
4. Server validates finite values, command allow-list, duration, and profile
   limits before allocation. Agent repeats equivalent policy validation.
5. Agent sends velocity for exactly the approved duration, then makes one
   best-effort `StopMove` request. Dispatch acknowledgement and elapsed
   duration are not proof of physical displacement.

## Lifecycle and failure semantics

Cancellation, timeout, capability revocation, stale evidence, or transport
loss reject new work. An active future motion needs one best-effort StopMove
request, whose failure must be retained with the primary failure. It is not a
hardware emergency stop. Network loss can prevent it from reaching the Robot.

## Rollout

Deploy parser and simulator support before any v2-producing frontend. Keep
allocation fail-closed unless verified `COMMAND_*` capability, reviewed profile,
fresh telemetry, identity evidence, and field approval exist. Rollback disables
v2 allocation; it does not mutate existing v1 revisions or database rows.
