# Testing

The local verification suite is intentionally small and deterministic:

```bash
python scripts/harness_check.py
ruff check .
ruff format --check .
mypy
pytest
```

Tests must not require a physical robot, robot network, secret, or a running Poppy-
Server unless a later Issue explicitly defines a separately controlled integration
test. Physical movement and posture commands are never test fixtures.

