# Architecture

The repository is intentionally small while the runtime contract is being established.

```text
src/poppy_agent/
├── config/   environment-backed settings
├── agent/    lifecycle coordination
└── robot/    RobotAdapter contract and implementations
```

The Agent core depends on the `RobotAdapter` contract, not on a concrete robot SDK.
The mock adapter and Poppy-Server transport are available for deterministic runtime
tests. Unitree remains a read-only telemetry boundary; Robot control methods are
outside the current automation scope.

Execution assignment transport maps validated assignment metadata to `ExecutionTask`.
In mock mode, the runtime reports `RUNNING`, passes the task to the deterministic
`MockExecutionExecutor`, and reports the returned final `ExecutionResult`. The mock
executor preflights the complete typed program through `ExecutionSafetyValidator`
before dispatching each command to a trace-only `MockCommandTarget`; `WAIT` is a
no-op, and `STOP` records itself before ending the program successfully. Unitree
mode keeps execution disabled until a safe robot execution adapter is implemented;
the current integration does not control a robot.

## Hardware command boundary

Execution code does not receive or construct vendor SDK objects. A command target
converts each safety-validated `HighLevelCommand` into a hardware-neutral
`HardwareCommandIntent` and passes it through the small `HardwareCommandPort`:

```text
HighLevelCommandProgram
    -> ExecutionSafetyValidator
    -> CommandExecutionTarget
    -> HardwareCommandIntent
    -> HardwareCommandPort
    -> MotionExecutionStrategy
    -> MotionPlan
    -> UnitreeCommandBackend
    -> UnitreeCommandClient
    -> FakeUnitreeCommandClient (current test double)
    -> real SDK client (disabled)
```

`MotionExecutionStrategy` is the explicit boundary for the unresolved semantic
conversion between Poppy distance/angle commands and a velocity-shaped SDK
operation. It requires an injected `MotionProfile` and produces a deterministic
`MotionPlan`; it has no production defaults and does not perform vendor-specific
conversion. `UnitreeCommandBackend` maps only explicitly supported cases and does
not map program STOP to physical `StopMove`. `FakeUnitreeCommandClient` is an
in-memory test double with call recording and deterministic failure injection; it
has no SDK, socket, DDS, or robot dependency. `UnitreeGo2Adapter` remains a
separate read-only telemetry adapter, and this boundary is not wired into
production Unitree mode.

Physical execution is additionally guarded by `PhysicalExecutionGate`. Its default
readiness is `BLOCKED`; the explicit `POPPY_ENABLE_PHYSICAL_EXECUTION` request cannot
override unresolved client, policy, approval, telemetry, observability, or hardware
validation requirements. See [`physical-readiness.md`](physical-readiness.md) for
the source-of-truth contract.

Execution cancellation is a separate software lifecycle path. The runtime polls
Server's authoritative Agent execution status while an executor runs and shares
an ExecutionCancellationToken with cooperative executors. A Server CANCELLED
state becomes an Agent CANCELLED result; it is not translated to Program STOP
or a physical emergency stop. See [`execution-cancellation.md`](execution-cancellation.md).

Agent startup also reconciles Server-owned active work before beginning heartbeat
and execution polling. An active `ASSIGNED` or `RUNNING` execution is marked
`FAILED` and its Robot is released by the Server; command payloads are never
replayed because progress is unknown. Discovery/reconciliation failures abort
startup. See [`execution-recovery.md`](execution-recovery.md).

During the runtime loop, transient Server transport failures move the runtime to
`DEGRADED`. New execution polling is blocked until a heartbeat confirms that the
Server is reachable again. If an execution was active, the local executor receives
a cooperative cancellation request and the existing Server recovery contract is
used after reconnection; commands are never replayed. Authentication and response
contract failures are not treated as transient outages. See
[`runtime-connectivity.md`](runtime-connectivity.md).
## Runtime observability

Agent runtime, execution, cancellation, recovery, and Server transport events use the
stable, secret-safe logging contract in [Runtime Observability Contract](runtime-observability.md).
This improves lifecycle visibility without enabling physical Unitree execution.
