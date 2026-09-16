# Motion Execution Strategy

## Scope

Poppy `MOVE` and `TURN` commands express a requested distance or angle. The
official Unitree Go2 high-level `Move(vx, vy, vyaw)` operation is velocity-shaped
and does not, by itself, define how a requested distance or angle should be
completed. This document defines the explicit planning boundary without enabling
physical execution.

```text
HardwareCommandIntent
    -> MotionExecutionStrategy
    -> MotionPlan
    -> UnitreeCommandBackend
    -> UnitreeCommandClient
    -> FakeUnitreeCommandClient (current phase)
    -> real SDK client (disabled)
```

The strategy creates a plan only. It does not open a connection, import the
Unitree SDK, publish DDS commands, or control a robot.

## Explicit motion profile

`MotionProfile` contains both a linear planning rate in meters per second and an
angular planning rate in degrees per second. There are no production defaults.
`MOVE` and `TURN` fail closed unless an explicit profile is injected.

Tests may inject clearly test-only values to verify deterministic arithmetic. A
test profile is not a Poppy operating limit, a Unitree recommendation, or an
approval to use a physical robot.

## MOVE

Poppy `MOVE` retains its direction and distance in meters. With an explicit
profile, the strategy creates a plan with:

```text
duration_seconds = distance_meters / linear_rate_meters_per_second
```

The plan retains the original Poppy units and direction. It does not invent a
Unitree velocity sign convention or convert the plan into SDK arguments. A future
hardware integration must separately review how a distance request is executed
using the SDK's velocity-shaped operation.

## TURN

Poppy `TURN` retains its direction and angle in degrees. With an explicit profile,
the strategy creates a plan with:

```text
duration_seconds = angle_degrees / angular_rate_degrees_per_second
```

The plan retains degrees and `LEFT`/`RIGHT`. No degree-to-radian conversion,
signed yaw convention, or physical angular-rate policy is assumed here. Those
decisions require an explicit reviewed execution strategy.

## Other commands

- `WAIT` is an execution-level operation and does not call a Unitree client.
  `RecordingSleeper` records a requested duration without sleeping in tests.
- `STOP` is a program-level terminator. It is not `StopMove` and is not a
  physical emergency stop.
- `POSTURE` keeps the existing explicit fake-client contract for `Sit` and
  `StandUp`; it does not enable hardware execution.
- `PRESET` remains unsupported until an explicit allow-list and mapping policy
  exist.

## Failure and preflight

The complete typed program is safety-preflighted before the first target dispatch.
The Unitree backend plans every `MOVE` and `TURN` during preflight, so a missing
profile, invalid profile, invalid command value, or impossible mapping leaves the
client trace empty. Client and backend failures become failed execution results;
they are never converted into `COMPLETED`.

The sleeper is an injected boundary. The current fake implementation is
non-blocking and records durations. A future implementation should remain
interruptible so administrative cancellation is not made impossible by an
uninterruptible sleep. Cancellation itself is outside this change.

## Physical enablement remains gated

No physical safety values are defined here. Maximum distance, speed, angle,
angular rate, acceleration, braking behavior, battery threshold, obstacle
distance, emergency-stop latency, and preset allow-list remain **TBD**.

The real Unitree client is not implemented or wired into `ROBOT_MODE=unitree`.
Hardware validation status: **NOT TESTED ON HARDWARE**.

## Official SDK references

The contract was checked against the official sources:

- [Unitree Python `SportClient`](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/sport/sport_client.py)
- [Official Go2 high-level Python example](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/go2/high_level/go2_sport_client.py)
- [Unitree C++ Go2 `SportClient` header](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp)

These sources establish the existence and shape of high-level operations; they
do not establish Poppy's physical operating limits or authorize command
execution.
