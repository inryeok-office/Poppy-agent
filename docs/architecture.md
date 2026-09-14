# Architecture

The repository is intentionally small while the runtime contract is being established.

```text
src/poppy_agent/
├── config/   environment-backed settings
├── agent/    lifecycle coordination
└── robot/    RobotAdapter contract and implementations
```

The Agent core depends on the `RobotAdapter` contract, not on a concrete robot SDK.
Phase 2 provides only `MockRobotAdapter`. Poppy-Server client and Unitree integration
are later boundaries added by separate Issues. Robot control methods are outside the
current automation scope.

Execution assignment transport is a future integration boundary. Once transport has
validated assignment status, it may map metadata to `ExecutionTask`, pass it to an
`ExecutionExecutor`, and use the returned final `ExecutionResult`. The current core
provides only a deterministic `MockExecutionExecutor`; it is not connected to the
runtime and does not control a robot.
