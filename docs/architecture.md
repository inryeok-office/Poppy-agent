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
executor dispatches each typed command to a trace-only `MockCommandTarget`; `WAIT` is
a no-op, and `STOP` records itself before ending the program successfully. Unitree
mode keeps execution disabled until a safe robot execution adapter is implemented;
the current integration does not control a robot.
