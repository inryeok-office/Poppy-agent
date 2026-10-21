# Motion protocol v2 compatibility matrix

## Canonical payload

Version 2 adds bounded open-loop velocity commands while preserving version 1
documents unchanged. The canonical payloads are:

```json
{"protocolVersion":2,"commands":[{"sequence":0,"sourceBlockId":"move-1","type":"MOVE","parameters":{"linearVelocityMetersPerSecond":-0.1,"durationSeconds":1.0}}]}
```

```json
{"protocolVersion":2,"commands":[{"sequence":0,"sourceBlockId":"turn-1","type":"TURN","parameters":{"angularVelocityDegreesPerSecond":15.0,"durationSeconds":1.0}}]}
```

Linear velocity is signed in metres per second: positive is the future
documented forward convention and negative is backward. Angular velocity is
signed in degrees per second, retaining Poppy's existing degree-facing
contract. `durationSeconds` is a positive finite duration measured by the
Agent with a monotonic clock. Lateral velocity is deliberately absent.

Neither dispatch acknowledgement nor elapsed duration asserts that a Robot
reached a requested position or heading. The Agent requests best-effort
`StopMove` after the duration; it is not a hardware emergency stop.

## Compatibility matrix

| Component | v1 | v2 in this branch | Rollout requirement |
| --- | --- | --- | --- |
| Stored project / Client editor | Preserved | Not yet produced | Add explicitly versioned blocks and validation; do not migrate old projects. |
| Server parser and serializer | Reads/writes v1 | Reads/writes v2, finite signed velocities and positive finite duration only | Deploy parser support before a producer. |
| Server compiler / allocation | Emits v1 today | Does not emit v2 yet | Add a selected v2 compiler path and command-specific capability allocation. |
| Agent parser / policy | Parses v1 | Parses v2 and validates policy again | Keep physical execution disabled until the rollout gates are approved. |
| Unitree backend | Explicitly rejects v1 MOVE/TURN | Fake-only velocity-duration dispatch path | Verify SDK yaw units/sign and hardware behavior before a production enablement. |
| Simulator | Existing v1 behavior preserved | Not implemented | Add deterministic velocity-times-duration estimation and label it open-loop. |

## Capability and rollback rules

The trusted code-owned mapping is `MOVE -> COMMAND_MOVE` and
`TURN -> COMMAND_TURN`. The Agent requires every capability required by the
delivered program to be `VERIFIED` in freshly fetched Agent-scoped evidence;
an environment variable cannot remap authority. This is distinct from
`TELEMETRY` verification and from operational readiness.

Unknown protocol versions, fields, command types, missing evidence, stale
evidence, and an unsupported v1 physical MOVE/TURN fail closed. Rollback is to
disable v2 production/allocation while retaining v1 parser support and stored
v1 project data. No database migration is required for the protocol parser
alone because execution payloads are persisted as JSON.

## Known non-guarantees

The Python process cannot forcibly terminate a blocking native SDK call after a
thread timeout. Active-command revocation/staleness is therefore documented as
a production-approval blocker until a reviewed executor/SDK isolation design
can request and verify a stop without claiming a hardware E-stop guarantee.
