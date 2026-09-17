"""Small, exception-safe cleanup helpers for software-only rehearsals."""

from __future__ import annotations

from collections.abc import Callable, Iterable


def run_cleanup_steps(
    steps: Iterable[tuple[str, Callable[[], None]]],
) -> list[str]:
    """Run every cleanup step and return safe, non-secret failure summaries."""

    failures: list[str] = []
    for name, action in steps:
        try:
            action()
        except Exception as exc:  # Cleanup must not prevent later steps.
            failures.append(f"{name}: {type(exc).__name__}")
    return failures
