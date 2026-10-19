# Physical command safety (hardware-free implementation)

This document describes code prepared for a future controlled physical test.
It does **not** authorize `POPPY_ENABLE_PHYSICAL_EXECUTION=true`, create a
production motion profile, or replace the vendor's physical emergency process.

## Current contract

- Physical execution remains fail-closed unless the existing readiness evidence
  is complete and a future reviewed caller supplies an explicit policy.
- The policy has no environment-selected production defaults.  Its
  `for_test()` values are fake-only regression fixtures, not approved operating
  limits.
- `MOVE` and `TURN` require an explicit allow-list, finite positive magnitude,
  rate, and duration, and are bounded by that supplied policy.
- `PRESET` stays denied unless the existing explicit protocol policy allows it.
- Poppy `STOP` remains program termination.  It is not silently redefined as a
  Robot transport command.

## Unitree StopMove

The installed SDK exposes `SportClient.StopMove()` (API 1003, no arguments,
integer status result).  The adapter invokes it only as best-effort cleanup for
an active planned MOVE/TURN on cancellation, dispatch failure, or executor
shutdown.  Failure is retained alongside the primary failure.

`StopMove` is a transport-dependent movement stop request.  It is **not** a
hardware emergency stop: it cannot be sent after power, Ethernet, DDS, process,
or network failure, and it does not replace the official controller or power
isolation procedure.

## Physical-test prerequisites not represented as approved defaults

Before any enablement review, a responsible operator must approve documented
numeric limits, command allow-list, allowed presets, battery threshold,
telemetry freshness threshold, Robot/Agent binding, capability policy, and
network-loss behavior.  The following field roles are required onsite:

- operator: performs exactly the approved procedure;
- observer: watches Robot posture, clearance, and people;
- power/controller responder: holds the vendor-approved physical emergency
  response and does not rely on software StopMove.

Use an empty, level test area, remove people and obstacles from the Robot's
clearance area, verify battery/telemetry/network beforehand, and retain a
tested rollback path.  No initial command, duration, velocity, distance, or
angle is approved by this document.

## Failure behavior

The implementation requests StopMove at most once for an active backend motion
and preserves both a primary dispatch/cancellation failure and any stop failure.
It cannot interrupt a blocking vendor call that never returns; this remains a
hardware-validation and vendor-contract requirement.  On transport loss, new
execution must remain gated by runtime connectivity/readiness; a physical
network-loss stop guarantee is not claimed.

## Validation scope

All coverage is fake-only.  No Unitree SDK client, DDS publisher/subscriber,
SportClient instance, or Robot command is created by these tests.
