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
  robot-control commands. The only exception is the controlled physical trial procedure
  below; even then an AI agent never sends robot commands itself.
- Unitree work is read-only telemetry only and must be based on official SDK material,
  except for the TURN-only controlled trial path defined by an approved Issue.
- If a required contract, dependency, permission, or safety condition is unclear, stop
  and report the blocker instead of adding a speculative workaround.

## Controlled physical trial exception

A physical trial is allowed only when every condition holds:

- Approval: the equipment owner (teacher) approves the trial in advance and is present.
  The approval is recorded and referenced by `POPPY_PHYSICAL_APPROVAL_REF`.
- Scope: one approved Issue defines the Robot, the command type, and the numeric limits.
  Limits record their source (administrator original value vs. proposed value).
- Single run: the Agent enforces a process-lifetime budget (`POPPY_PHYSICAL_MAX_COMMANDS`);
  no automatic retry and no second run without a new approval.
- Observers: at least two observers, a cleared area, and a remote controller in hand.
- Damping procedure: on any abnormal motion, switch to Damping with the remote, wait
  three minutes, power off if safe, then remove the battery.
- Records: observed direction and angle, stop behavior, execution status and ID, and a
  secret-free Agent log summary are committed under `docs/` after the trial.
- AI agents only implement and test with fakes. Physical enablement, systemd control,
  EnvironmentFile edits, and the run itself are performed by a human operator.

## Verification

Before commit and push, run the harness check, `ruff check .`, `ruff format --check .`,
`mypy`, and `pytest`. A failing check must be fixed or reported; it must not be hidden.
Keep documentation and tests aligned with every behavior change.

## Language and encoding

- Commit subject, PR title/body, Issue text, review explanations, and development
  documents use Korean by default.
- Conventional Commit `type(scope)`, code identifiers, paths, API names, commands,
  and external product names may remain in their original form.
- Store repository text files as UTF-8 without a BOM. Do not submit GitHub text that
  contains `?`, `??`, `U+FFFD`, or other encoding replacement artifacts.
