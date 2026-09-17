"""Machine-readable operational status for the Poppy-Agent runtime."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from uuid import UUID

from poppy_agent.observability import (
    OPERATIONAL_STATUS_PUBLISH_FAILED,
    log_event,
    safe_exception_type,
)

logger = logging.getLogger(__name__)


class RuntimeConnectivityState(StrEnum):
    """Server connectivity state used to gate new execution polling."""

    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"


class RuntimeLifecycleState(StrEnum):
    """Local Agent process lifecycle state."""

    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class OperationalReadinessReason(StrEnum):
    """Stable machine-readable reasons why operational readiness is false."""

    NOT_REGISTERED = "NOT_REGISTERED"
    STARTUP_RECOVERY_PENDING = "STARTUP_RECOVERY_PENDING"
    SERVER_CONNECTIVITY_DEGRADED = "SERVER_CONNECTIVITY_DEGRADED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RUNTIME_STARTING = "RUNTIME_STARTING"
    RUNTIME_STOPPING = "RUNTIME_STOPPING"
    RUNTIME_FAILED = "RUNTIME_FAILED"


@dataclass(frozen=True, slots=True)
class AgentOperationalSnapshot:
    """Consistent, secret-free point-in-time view of Agent operation."""

    schema_version: int
    observed_at: datetime
    lifecycle_state: RuntimeLifecycleState
    connectivity_state: RuntimeConnectivityState
    liveness: bool
    registered: bool
    agent_id: UUID | None
    robot_id: UUID | None
    active_execution_id: UUID | None
    recovery_complete: bool
    operational_ready: bool
    accepting_new_execution: bool
    readiness_reasons: tuple[OperationalReadinessReason, ...]
    last_server_success_at: datetime | None
    last_heartbeat_success_at: datetime | None

    def to_dict(self) -> dict[str, object]:
        """Return the stable camelCase JSON representation."""

        return {
            "schemaVersion": self.schema_version,
            "observedAt": self.observed_at.isoformat(),
            "lifecycleState": self.lifecycle_state.value,
            "connectivityState": self.connectivity_state.value,
            "liveness": self.liveness,
            "registered": self.registered,
            "agentId": _uuid_value(self.agent_id),
            "robotId": _uuid_value(self.robot_id),
            "activeExecutionId": _uuid_value(self.active_execution_id),
            "recoveryComplete": self.recovery_complete,
            "operationalReady": self.operational_ready,
            "acceptingNewExecution": self.accepting_new_execution,
            "readinessReasons": [reason.value for reason in self.readiness_reasons],
            "lastServerSuccessAt": _datetime_value(self.last_server_success_at),
            "lastHeartbeatSuccessAt": _datetime_value(self.last_heartbeat_success_at),
        }


class OperationalStatusTracker:
    """Thread-safe mutable state that produces immutable operational snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._lifecycle_state = RuntimeLifecycleState.STARTING
        self._connectivity_state = RuntimeConnectivityState.CONNECTED
        self._registered = False
        self._agent_id: UUID | None = None
        self._robot_id: UUID | None = None
        self._active_execution_id: UUID | None = None
        self._recovery_complete = False
        self._execution_polling_enabled = False
        self._authentication_failed = False
        self._last_server_success_at: datetime | None = None
        self._last_heartbeat_success_at: datetime | None = None

    def mark_registered(self, agent_id: UUID, robot_id: UUID, *, at: datetime) -> None:
        with self._lock:
            self._registered = True
            self._agent_id = agent_id
            self._robot_id = robot_id
            self._last_server_success_at = at

    def mark_recovery_complete(self) -> None:
        with self._lock:
            self._recovery_complete = True

    def mark_server_success(self, *, heartbeat: bool = False, at: datetime) -> None:
        with self._lock:
            self._last_server_success_at = at
            if heartbeat:
                self._last_heartbeat_success_at = at

    def set_connectivity(self, state: RuntimeConnectivityState) -> None:
        with self._lock:
            self._connectivity_state = state

    def set_lifecycle(self, state: RuntimeLifecycleState) -> None:
        with self._lock:
            self._lifecycle_state = state

    def mark_authentication_failed(self) -> None:
        with self._lock:
            self._authentication_failed = True
            self._lifecycle_state = RuntimeLifecycleState.FAILED

    def set_active_execution(self, execution_id: UUID | None) -> None:
        with self._lock:
            self._active_execution_id = execution_id

    def set_execution_polling_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._execution_polling_enabled = enabled

    def snapshot(self, *, observed_at: datetime | None = None) -> AgentOperationalSnapshot:
        observed = observed_at or datetime.now(UTC)
        with self._lock:
            lifecycle = self._lifecycle_state
            connectivity = self._connectivity_state
            registered = self._registered
            agent_id = self._agent_id
            robot_id = self._robot_id
            active_execution_id = self._active_execution_id
            recovery_complete = self._recovery_complete
            polling_enabled = self._execution_polling_enabled
            authentication_failed = self._authentication_failed
            last_server_success_at = self._last_server_success_at
            last_heartbeat_success_at = self._last_heartbeat_success_at

        reasons: list[OperationalReadinessReason] = []
        if not registered:
            reasons.append(OperationalReadinessReason.NOT_REGISTERED)
        if not recovery_complete:
            reasons.append(OperationalReadinessReason.STARTUP_RECOVERY_PENDING)
        if connectivity is RuntimeConnectivityState.DEGRADED:
            reasons.append(OperationalReadinessReason.SERVER_CONNECTIVITY_DEGRADED)
        if authentication_failed:
            reasons.append(OperationalReadinessReason.AUTHENTICATION_FAILED)
        if lifecycle is RuntimeLifecycleState.STARTING:
            reasons.append(OperationalReadinessReason.RUNTIME_STARTING)
        elif lifecycle in {RuntimeLifecycleState.STOPPING, RuntimeLifecycleState.STOPPED}:
            reasons.append(OperationalReadinessReason.RUNTIME_STOPPING)
        elif lifecycle is RuntimeLifecycleState.FAILED:
            reasons.append(OperationalReadinessReason.RUNTIME_FAILED)

        operational_ready = lifecycle is RuntimeLifecycleState.READY and not reasons
        accepting_new_execution = (
            operational_ready and polling_enabled and active_execution_id is None
        )
        return AgentOperationalSnapshot(
            schema_version=1,
            observed_at=observed,
            lifecycle_state=lifecycle,
            connectivity_state=connectivity,
            liveness=lifecycle not in {RuntimeLifecycleState.STOPPED, RuntimeLifecycleState.FAILED},
            registered=registered,
            agent_id=agent_id,
            robot_id=robot_id,
            active_execution_id=active_execution_id,
            recovery_complete=recovery_complete,
            operational_ready=operational_ready,
            accepting_new_execution=accepting_new_execution,
            readiness_reasons=tuple(reasons),
            last_server_success_at=last_server_success_at,
            last_heartbeat_success_at=last_heartbeat_success_at,
        )


class StatusSnapshotPublisher:
    """Publish snapshots with same-directory temporary file replacement."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None

    def publish(self, snapshot: AgentOperationalSnapshot) -> None:
        if self.path is None:
            return
        temporary_name: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(snapshot.to_dict(), temporary, ensure_ascii=False, separators=(",", ":"))
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.path)
        except OSError as exc:
            log_event(
                logger,
                logging.ERROR,
                OPERATIONAL_STATUS_PUBLISH_FAILED,
                error_type=safe_exception_type(exc),
            )
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self) -> None:
        if self.path is None:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            log_event(
                logger,
                logging.WARNING,
                OPERATIONAL_STATUS_PUBLISH_FAILED,
                error_type=safe_exception_type(exc),
            )


def _uuid_value(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
