# AI workflow

AI-assisted changes follow the same repository controls as human-authored changes.

## Instruction priority

1. Current user instruction
2. Approved GitHub Issue
3. `CLAUDE.md` and `AGENTS.md`
4. Repository documentation
5. Existing code conventions

Before changing code, confirm the Issue, completion conditions, current branch,
working-tree state, relevant documentation, impact area, and existing tests.

AI must not invent an unclear server contract or SDK API, add future command
interfaces, hide failed checks, expose secrets, or reverse user changes. When an
external dependency, contract, permission, or safety boundary is unclear, stop and
report the blocker.

