# Poppy-Agent development harness

This document is shared by Claude Code and Codex. `CLAUDE.md` and `AGENTS.md` must
remain byte-identical and LF-only; the repository harness checks this condition.

## Instruction priority

1. Current user instruction
2. Approved GitHub Issue
3. `CLAUDE.md` and `AGENTS.md`
4. Repository documentation
5. Existing code conventions

## Required workflow

Before changing code, confirm the Issue and its completion conditions, update from the
latest `develop`, inspect `git status`, read relevant documentation, assess the impact
area, and inspect existing tests. Each change follows Issue -> branch/worktree ->
implementation -> verification -> commit -> push -> pull request to `develop` -> CI
and review -> squash merge -> Issue closure -> refresh `develop`.

Use `feature/`, `fix/`, `refactor/`, `chore/`, or `docs/` branches named with the Issue
number and a kebab-case short name. Do not commit or push directly to `main` or
`develop`. Do not automatically merge pull requests targeting `main`.

## Scope and safety

- Keep each PR within one Issue; avoid unrelated refactors, formatting, or abstractions.
- Do not invent unclear Poppy-Server contracts or Unitree SDK APIs.
- Do not add unused interfaces or future robot command methods.
- Never commit or log tokens, IP addresses, credentials, or site-specific settings.
- Preserve user changes and do not use destructive Git commands.
- Never execute or test physical movement, turning, posture, actuator, motor, or other
  robot-control commands.
- Unitree work is read-only telemetry only and must be based on official SDK material.
- If a required contract, dependency, permission, or safety condition is unclear, stop
  and report the blocker instead of adding a speculative workaround.

## Verification

Before commit and push, run the harness check, `ruff check .`, `ruff format --check .`,
`mypy`, and `pytest`. A failing check must be fixed or reported; it must not be hidden.
Keep documentation and tests aligned with every behavior change.

