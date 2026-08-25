# Continuous integration

The CI workflow runs for pushes and pull requests targeting `main` or `develop`.
It uses Python 3.11 and grants only `contents: read`.

The checks are:

1. Install the package and development dependencies.
2. Run the repository harness check.
3. Run Ruff lint and format checks.
4. Run mypy.
5. Run pytest.

The same checks should pass locally before opening a pull request. CI failures must be
fixed or reported as blockers; they must not be hidden or bypassed.

