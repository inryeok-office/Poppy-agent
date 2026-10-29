# Configuration

Configuration is supplied through the environment rather than committed files.
`.env.example` documents names and local placeholders only.

Current placeholders:

- `ROBOT_MODE`: future adapter selection, expected values include `mock` and `unitree`
- `POPPY_ROBOT_ID`: explicit robot identity used by the selected adapter
- `POPPY_ENABLE_PHYSICAL_EXECUTION`: physical execution request; defaults to `false` and does not bypass readiness requirements
- `POPPY_SERVER_URL`: Poppy-Server base URL
- `POPPY_AGENT_TOKEN`: Poppy-Server authentication token
- `POPPY_AGENT_NAME`, `POPPY_AGENT_VERSION`, `POPPY_SDK_VERSION`, `POPPY_AGENT_PLATFORM`: register metadata
- `POPPY_HEARTBEAT_INTERVAL_SECONDS`: Agent heartbeat interval; the 30-second value in `.env.example` is a development default, not an offline timeout
- `POPPY_EXECUTION_POLL_INTERVAL_SECONDS`: Mock-mode execution polling interval; the default is 1 second
- `POPPY_SERVER_CONNECT_TIMEOUT_SECONDS`, `POPPY_SERVER_READ_TIMEOUT_SECONDS`: HTTP timeouts
- `POPPY_SERVER_MAX_RETRIES`: bounded transport retry count
- `POPPY_SERVER_RECONNECT_INITIAL_DELAY_SECONDS`: runtime reconnect backoff initial delay
- `POPPY_SERVER_RECONNECT_MAX_DELAY_SECONDS`: runtime reconnect backoff upper bound
- `POPPY_RUNTIME_STATUS_PATH`: optional local JSON status path. When set, the Agent
  publishes an atomic operational snapshot; the systemd example uses
  `/run/poppy-agent/status.json`.
- `UNITREE_NETWORK_INTERFACE`: Linux network interface passed to the official SDK, such as `enp2s0`
- `POPPY_ROBOT_MODEL`, `POPPY_ROBOT_EDITION`, `POPPY_ROBOT_FIRMWARE_VERSION`: explicit Unitree identity metadata when the SDK does not provide it
- `UNITREE_SDK_VERSION`: explicit Unitree SDK metadata for registration
- `POPPY_UNITREE_TELEMETRY_STALE_TIMEOUT_SECONDS`: required positive finite timeout
  for Unitree low-state freshness. A stale or absent snapshot reports the Robot as
  `OFFLINE`; it is not a physical safety limit. The approved GO2EDU001 deployment
  value is `5.0` seconds; an existing Unitree EnvironmentFile must receive this
  non-secret key before this Agent version is started.
- `POPPY_PHYSICAL_TRIAL_MODE`, `POPPY_PHYSICAL_TURN_RATE_DEG_PER_S`,
  `POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND`, `POPPY_PHYSICAL_MAX_TOTAL_TURN_DEG`,
  `POPPY_PHYSICAL_MAX_TOTAL_SECONDS`, `POPPY_PHYSICAL_MAX_COMMANDS`,
  `POPPY_PHYSICAL_ALLOWED_COMMANDS`, `POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN`,
  `POPPY_PHYSICAL_APPROVAL_REF`: controlled TURN trial values. They have no defaults;
  see [`controlled-turn-trial.md`](controlled-turn-trial.md) for ranges and sources.

Phase 2 consumes `ROBOT_MODE` and `POPPY_ROBOT_ID` only. Phase 3 additionally requires
the server URL, token, and register metadata. Both `ROBOT_MODE` and `POPPY_ROBOT_ID`
must be present, and the supported modes are explicitly selected `mock` and `unitree`.
`mock` mode enables Execution polling and the deterministic Mock Executor. `unitree`
mode is heartbeat-only unless the controlled TURN trial is enabled and every
`POPPY_PHYSICAL_*` trial key is valid; see [`controlled-turn-trial.md`](controlled-turn-trial.md).
A blocked physical configuration never stops the process: it keeps heartbeating as
`UNAVAILABLE` and publishes the reasons under `physicalExecution` in the status file.
There is no implicit fake-robot default. The physical execution request flag does not
enable execution by itself; the readiness contract must also be satisfied. The token
is never logged or committed.
The Unitree adapter requires an explicit network interface when that adapter is
selected; it does not guess a host interface.

Reconnect delays must be finite and positive, with the maximum at least as large
as the initial delay. They control software reconnect pacing only; they are not
hardware safety limits or offline-timeout policy.
