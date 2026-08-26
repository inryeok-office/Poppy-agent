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
