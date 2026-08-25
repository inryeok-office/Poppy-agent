# Configuration

Configuration is supplied through the environment rather than committed files.
`.env.example` documents names and local placeholders only.

Current placeholders:

- `ROBOT_MODE`: future adapter selection, expected values include `mock` and `unitree`
- `POPPY_ROBOT_ID`: explicit robot identity used by the selected adapter
- `POPPY_SERVER_URL`: future server base URL
- `POPPY_AGENT_TOKEN`: future server authentication token

Phase 2 consumes `ROBOT_MODE` and `POPPY_ROBOT_ID` only. Both must be present, and the
only supported mode is the explicitly selected `mock` adapter. There is no implicit
fake-robot default. Later phases must define validation and defaults in an approved
Issue before using additional values. Development defaults must not be mistaken for
production connectivity or hardware state.
