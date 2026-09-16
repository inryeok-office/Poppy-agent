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
    -> FakeHardwareBackend (current test double)
    -> future vendor backend (disabled)
```

`FakeHardwareBackend` is an in-memory test double with explicit support, lifecycle,
trace, and deterministic failure injection. It has no SDK, socket, DDS, or robot
dependency. `UnitreeGo2Adapter` remains a separate read-only telemetry adapter;
this boundary is not wired into production Unitree mode.
