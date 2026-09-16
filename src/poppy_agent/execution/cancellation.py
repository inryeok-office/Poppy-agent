"""Cooperative, hardware-independent execution cancellation primitives."""

from __future__ import annotations

import time
from threading import Event, Lock
from typing import Protocol


class ExecutionCancelledError(RuntimeError):
    """Raised when an execution observes an external cancellation request."""


class ExecutionCancellationToken:
    """Thread-safe cancellation signal shared by runtime and executor."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason = "execution cancelled"

    def cancel(self, reason: str = "execution cancelled") -> None:
        """Request cooperative cancellation; repeated requests are harmless."""
        with self._lock:
            if not self._event.is_set():
                self._reason = reason
                self._event.set()

    def is_cancelled(self) -> bool:
        """Return whether cancellation was requested."""
        return self._event.is_set()

    @property
    def reason(self) -> str:
        """Return a non-secret diagnostic reason for local result handling."""
        with self._lock:
            return self._reason

    def raise_if_cancelled(self) -> None:
        """Raise at a cooperative execution boundary when cancelled."""
        if self._event.is_set():
            raise ExecutionCancelledError(self.reason)

    def wait(self, timeout_seconds: float) -> bool:
        """Wait interruptibly and return whether cancellation was observed."""
        return self._event.wait(timeout_seconds)


class CancellationSleeper(Protocol):
    """Timing boundary that can be interrupted by an execution token."""

    def sleep(
        self,
        duration_seconds: float,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> None:
        """Wait or record a duration without owning a robot resource."""


class InterruptibleSleeper:
    """Wall-clock sleeper for future integrations; it never controls hardware."""

    def sleep(
        self,
        duration_seconds: float,
        cancellation_token: ExecutionCancellationToken | None = None,
    ) -> None:
        """Wait for a duration unless the token requests cancellation."""
        if cancellation_token is None:
            time.sleep(duration_seconds)
            return
        if cancellation_token.wait(duration_seconds):
            cancellation_token.raise_if_cancelled()


__all__ = [
    "CancellationSleeper",
    "ExecutionCancellationToken",
    "ExecutionCancelledError",
    "InterruptibleSleeper",
]
