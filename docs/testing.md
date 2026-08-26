# Testing

The local verification suite is intentionally small and deterministic:

```bash
python scripts/harness_check.py
ruff check .
ruff format --check .
mypy
pytest
```

Phase 2 tests cover configuration validation, Mock Robot initialization and state,
adapter capabilities, Agent startup, and graceful shutdown. Phase 3 tests use an
in-process HTTP transport to cover request/header mapping, response parsing, nullable
heartbeat fields, HTTP errors, timeout/connection failures, and malformed responses.
Tests must not require a physical robot, robot network, secret, or a running
Poppy-Server unless a later Issue explicitly defines a separately controlled
integration test. Unitree adapter tests use a fake SDK module and never initialize DDS.
Physical movement and posture commands are never test fixtures.
