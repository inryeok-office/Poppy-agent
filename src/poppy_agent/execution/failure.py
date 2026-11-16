"""Stable, secret-free Execution failure codes (#101).

Codes classify why an Execution FAILED without exposing SDK details.  Errors
carry a ``failure_code`` attribute where they are raised; anything without one
is ``EXECUTION_ERROR``.  Reporting the code to Poppy-Server waits for the Server
contract (Poppy-Server#134); until then it is recorded locally in the result and
the structured ``execution_failed`` log.
"""

from __future__ import annotations

from enum import StrEnum


class FailureCode(StrEnum):
    SAFETY_REJECTED = "SAFETY_REJECTED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    TELEMETRY_STALE = "TELEMETRY_STALE"
    POSTURE_UNKNOWN = "POSTURE_UNKNOWN"
    SDK_REJECTED = "SDK_REJECTED"
    TIMEOUT = "TIMEOUT"
    NOT_MOVED = "NOT_MOVED"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class CodedError(RuntimeError):
    """RuntimeError that may carry a ``FailureCode`` set where it is raised."""

    failure_code: FailureCode | None = None

    def __init__(self, *args: object, failure_code: FailureCode | None = None) -> None:
        super().__init__(*args)
        if failure_code is not None:
            self.failure_code = failure_code


def failure_code_of(exc: BaseException | None, default: FailureCode) -> FailureCode:
    """Return the first ``failure_code`` along the cause chain, else ``default``."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        code = getattr(exc, "failure_code", None)
        if isinstance(code, FailureCode):
            return code
        exc = exc.__cause__
    return default


__all__ = ["CodedError", "FailureCode", "failure_code_of"]
