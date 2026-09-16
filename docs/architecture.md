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
