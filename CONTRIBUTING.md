# Contributing

## Workflow

1. Confirm the approved Issue and its completion conditions.
2. Update from the latest `develop`.
3. Create `feature/`, `fix/`, `refactor/`, `chore/`, or `docs/` work in an Issue-specific branch.
4. Keep the change within the Issue scope and preserve existing user changes.
5. Run the full local verification suite.
6. Open a pull request targeting `develop` and link the Issue with `Closes #N`.
7. Merge only after CI and review requirements pass, using squash merge.

Do not commit directly to `main` or `develop`. Do not add speculative APIs, unused
abstractions, or unrelated formatting changes. The physical robot safety boundary in
`AGENTS.md` applies to every contribution.

## Commit messages

Use Conventional Commits, for example `chore(init): agent development environment`.
Keep the subject concise, noun-focused, and free of a trailing period.

