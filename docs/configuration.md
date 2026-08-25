# Configuration

Configuration is supplied through the environment rather than committed files.
`.env.example` documents names and local placeholders only.

Current placeholders:

- `ROBOT_MODE`: future adapter selection, expected values include `mock` and `unitree`
- `POPPY_SERVER_URL`: future server base URL
- `POPPY_AGENT_TOKEN`: future server authentication token

Phase 1 does not consume these values. Later phases must define validation and defaults
in an approved Issue before using them. Development defaults must not be mistaken for
production connectivity or hardware state.

