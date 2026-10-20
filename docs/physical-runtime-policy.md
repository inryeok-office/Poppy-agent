# Physical runtime policy contract

This is a future enablement contract.  The current deployment must keep
`POPPY_ENABLE_PHYSICAL_EXECUTION=false`; no value in this document grants a
physical-motion approval.

When that flag is `false` or absent, no physical policy variables are required
and no Unitree command client is constructed.  When it is `true`, every item
below is required before the readiness gate is considered; absent, empty,
non-finite, or out-of-range input fails configuration before an SDK factory is
called.

| Variable | Unit / meaning |
| --- | --- |
| `POPPY_PHYSICAL_MOTION_PROFILE_NAME` | approved profile identifier, not a secret |
| `POPPY_PHYSICAL_MOTION_PROFILE_VERSION` | approved profile revision |
| `POPPY_PHYSICAL_ALLOWED_COMMANDS` | comma list containing only `MOVE` and/or `TURN` |
| `POPPY_PHYSICAL_MAX_MOVE_DISTANCE_METERS` | positive meters |
| `POPPY_PHYSICAL_MAX_TURN_ANGLE_DEGREES` | positive degrees |
| `POPPY_PHYSICAL_MAX_LINEAR_RATE_METERS_PER_SECOND` | positive m/s |
| `POPPY_PHYSICAL_MAX_ANGULAR_RATE_DEGREES_PER_SECOND` | positive deg/s |
| `POPPY_PHYSICAL_MAX_COMMAND_DURATION_SECONDS` | positive seconds |
| `POPPY_PHYSICAL_MIN_BATTERY_PERCENT` | integer 0 through 100 |

There are intentionally no production defaults.  The project has no approved
numeric limits, capability-verification query, vendor-call deadline guarantee,
or physical emergency evidence yet.

## Status JSON

Schema version 3 adds secret-free fields:

- `physicalExecutionEnabled`;
- `physicalReadiness.ready` and `physicalReadiness.blockers`;
- profile name/version when configured;
- placeholder evidence fields for telemetry, battery, capability and identity.

Those placeholder values are `null` until an approved runtime evidence source
exists.  They must not be interpreted as successful capability verification or
motion approval.  Existing status fields remain additive and unchanged.

## Distance/angle and Unitree velocity

Poppy commands currently carry distance in meters and angle in degrees.  The
installed SDK's `Move(vx, vy, vyaw)` accepts velocity-shaped values and does
not provide an acknowledged distance/angle completion contract.  Therefore no
distance/duration-to-velocity production mapper is implemented.  A future
review must define monotonic-time duration ownership, post-duration StopMove,
velocity signs, vendor units, and handling for a blocking call that cannot be
forcibly cancelled by Python.

`asyncio.wait_for` cannot terminate a thread that remains inside a vendor call.
A later design must use a bounded worker/process boundary and state explicitly
what happens if StopMove cannot be sent after Ethernet, DDS, or process loss.
