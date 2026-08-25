# Git workflow

## Branches

| Branch | Purpose |
| --- | --- |
| `main` | Stable, releasable state |
| `develop` | Next integration state |
| `feature/{issue-number}-{short-name}` | New capability |
| `fix/{issue-number}-{short-name}` | Bug correction |
| `refactor/{issue-number}-{short-name}` | Internal restructuring |
| `chore/{issue-number}-{short-name}` | Tooling or maintenance |
| `docs/{issue-number}-{short-name}` | Documentation-only work |

All work branches start from the latest `develop`. Direct commits and pushes to
`main` and `develop` are prohibited after repository initialization.

## Integration

Issue -> branch/worktree -> implementation -> tests -> pull request to `develop` ->
CI/review -> squash merge -> Issue closure -> refresh `develop`.

Do not merge a failing CI run, bypass required approvals, or automatically merge a
pull request targeting `main`.

