# Poppy-Agent

Poppy-Agent is the Python runtime boundary between a Poppy robot and Poppy-Server.
The repository is being built incrementally. The current baseline contains an Agent
lifecycle core, a development-only Mock Robot Adapter, and a contract-bound
Poppy-Server client. It does not require a running server, Unitree SDK2, or a physical
robot for local tests.

## Requirements

- Python 3.11
- Git

The Python version is intentionally pinned to the current project baseline. Unitree
SDK compatibility will be checked from official sources before any SDK dependency is
introduced.

## Local setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m poppy_agent.main
```

Copy `.env.example` to a local, untracked `.env` only when a later phase needs
configuration. Never commit tokens, robot addresses, or other site-specific values.

Phase 2 configuration requires `ROBOT_MODE=mock` and an explicit
`POPPY_ROBOT_ID`. The mock adapter is never selected implicitly for a production
runtime.

## Verification

```bash
python scripts/harness_check.py
ruff check .
ruff format --check .
mypy
pytest
```

Windows users can run `scripts/harness-check.ps1`; CI runs the same checks on pull
requests targeting `main` or `develop`.

## Development boundaries

- Every implementation change starts from an approved GitHub Issue and a current
  `develop` branch.
- Work is merged into `develop` by squash merge through a pull request.
- `main` is never automatically merged.
- This project does not issue physical robot movement, posture, actuator, or motor
  commands.
- Unitree integration, when introduced, is read-only telemetry first.

See `CONTRIBUTING.md`, `SECURITY.md`, and `docs/` for repository rules.
