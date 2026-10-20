"""Fail-closed cache for administrator-owned physical capability evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from time import monotonic
from typing import Protocol
from uuid import UUID


class CapabilityEvidenceFailure(StrEnum):
    """Secret-free classes for a failed evidence lookup."""

    NONE = "NONE"
    AUTHENTICATION = "AUTHENTICATION"
    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_FOUND = "NOT_FOUND"
    SERVER = "SERVER"
    TRANSPORT = "TRANSPORT"
    MALFORMED = "MALFORMED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


class CapabilityEvidenceClient(Protocol):
    def get_capability_evidence(
        self, agent_id: UUID, robot_id: UUID, *, timeout_seconds: float | None = None
    ) -> CapabilityEvidenceResponse: ...


class CapabilityEvidenceResponse(Protocol):
    robot_id: UUID

    def verified(self, code: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class CapabilityEvidencePolicy:
    required_code: str
    refresh_interval_seconds: float
    ttl_seconds: float
    request_timeout_seconds: float

    def __post_init__(self) -> None:
        if not self.required_code.strip():
            raise ValueError("required capability code must not be blank")
        for name, value in (
            ("refresh interval", self.refresh_interval_seconds),
            ("TTL", self.ttl_seconds),
            ("request timeout", self.request_timeout_seconds),
        ):
            if type(value) not in (int, float) or not isfinite(float(value)) or value <= 0:
                raise ValueError(f"capability evidence {name} must be a positive finite number")
        if self.ttl_seconds <= self.refresh_interval_seconds:
            raise ValueError("capability evidence TTL must exceed refresh interval")


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceSnapshot:
    robot_id: UUID
    required_code: str
    verified: bool
    checked_monotonic: float | None
    failure: CapabilityEvidenceFailure

    def fresh(self, *, now: float, ttl_seconds: float) -> bool:
        return (
            self.failure is CapabilityEvidenceFailure.NONE
            and self.checked_monotonic is not None
            and now - self.checked_monotonic <= ttl_seconds
        )


class CapabilityEvidenceCache:
    """Monotonic evidence cache; failures never retain an authorization grant."""

    def __init__(
        self,
        policy: CapabilityEvidencePolicy,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._snapshot: CapabilityEvidenceSnapshot | None = None

    def clear(self) -> None:
        self._snapshot = None

    def snapshot(self, robot_id: UUID) -> CapabilityEvidenceSnapshot:
        if self._snapshot is None or self._snapshot.robot_id != robot_id:
            return CapabilityEvidenceSnapshot(
                robot_id=robot_id,
                required_code=self.policy.required_code,
                verified=False,
                checked_monotonic=None,
                failure=CapabilityEvidenceFailure.NONE,
            )
        return self._snapshot

    def ready(self, robot_id: UUID) -> bool:
        snapshot = self.snapshot(robot_id)
        return snapshot.verified and snapshot.fresh(
            now=self._clock(), ttl_seconds=self.policy.ttl_seconds
        )

    def due(self, robot_id: UUID) -> bool:
        snapshot = self.snapshot(robot_id)
        if snapshot.checked_monotonic is None:
            return True
        return self._clock() - snapshot.checked_monotonic >= self.policy.refresh_interval_seconds

    def refresh(
        self, client: CapabilityEvidenceClient, agent_id: UUID, robot_id: UUID
    ) -> CapabilityEvidenceSnapshot:
        try:
            evidence = client.get_capability_evidence(
                agent_id, robot_id, timeout_seconds=self.policy.request_timeout_seconds
            )
        except Exception as exc:
            self._snapshot = CapabilityEvidenceSnapshot(
                robot_id=robot_id,
                required_code=self.policy.required_code,
                verified=False,
                checked_monotonic=self._clock(),
                failure=_failure_category(exc),
            )
            return self._snapshot
        if evidence.robot_id != robot_id:
            self._snapshot = CapabilityEvidenceSnapshot(
                robot_id=robot_id,
                required_code=self.policy.required_code,
                verified=False,
                checked_monotonic=self._clock(),
                failure=CapabilityEvidenceFailure.IDENTITY_MISMATCH,
            )
            return self._snapshot
        self._snapshot = CapabilityEvidenceSnapshot(
            robot_id=robot_id,
            required_code=self.policy.required_code,
            verified=evidence.verified(self.policy.required_code),
            checked_monotonic=self._clock(),
            failure=CapabilityEvidenceFailure.NONE,
        )
        return self._snapshot


def _failure_category(exc: Exception) -> CapabilityEvidenceFailure:
    from poppy_agent.server.client import ServerApiError, ServerResponseError, ServerTransportError

    if isinstance(exc, ServerApiError):
        return {
            401: CapabilityEvidenceFailure.AUTHENTICATION,
            403: CapabilityEvidenceFailure.ACCESS_DENIED,
            404: CapabilityEvidenceFailure.NOT_FOUND,
        }.get(exc.status_code, CapabilityEvidenceFailure.SERVER)
    if isinstance(exc, ServerTransportError):
        return CapabilityEvidenceFailure.TRANSPORT
    if isinstance(exc, ServerResponseError):
        return CapabilityEvidenceFailure.MALFORMED
    return CapabilityEvidenceFailure.SERVER


__all__ = [
    "CapabilityEvidenceCache",
    "CapabilityEvidenceClient",
    "CapabilityEvidenceFailure",
    "CapabilityEvidencePolicy",
    "CapabilityEvidenceSnapshot",
]
