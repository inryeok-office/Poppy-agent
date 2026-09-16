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
- `UNITREE_NETWORK_INTERFACE`: Linux network interface passed to the official SDK, such as `enp2s0`
- `POPPY_ROBOT_MODEL`, `POPPY_ROBOT_EDITION`, `POPPY_ROBOT_FIRMWARE_VERSION`: explicit Unitree identity metadata when the SDK does not provide it
- `UNITREE_SDK_VERSION`: explicit Unitree SDK metadata for registration

Phase 2 consumes `ROBOT_MODE` and `POPPY_ROBOT_ID` only. Phase 3 additionally requires
the server URL, token, and register metadata. Both `ROBOT_MODE` and `POPPY_ROBOT_ID`
must be present, and the supported modes are explicitly selected `mock` and `unitree`.
Only `mock` mode enables Execution polling and the deterministic Mock Executor. `unitree`
mode retains registration and heartbeat only until a safe execution adapter is implemented.
There is no implicit fake-robot default. The physical execution request flag does not
enable execution by itself; the readiness contract must also be satisfied. The token
is never logged or committed.
The Unitree adapter requires an explicit network interface when that adapter is
selected; it does not guess a host interface.
