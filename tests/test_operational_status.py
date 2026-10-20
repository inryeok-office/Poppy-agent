from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from json import loads
from uuid import UUID

import pytest

from poppy_agent.operational_status import (
    LocalTelemetryEvidence,
    OperationalReadinessReason,
    OperationalStatusTracker,
    RuntimeConnectivityState,
    RuntimeLifecycleState,
    StatusSnapshotPublisher,
)

AGENT_ID = UUID("00000000-0000-0000-0000-000000000001")
ROBOT_ID = UUID("00000000-0000-0000-0000-000000000002")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)


def ready_tracker() -> OperationalStatusTracker:
    tracker = OperationalStatusTracker()
    tracker.mark_registered(AGENT_ID, ROBOT_ID, at=NOW)
    tracker.mark_recovery_complete()
    tracker.set_execution_polling_enabled(True)
    tracker.set_lifecycle(RuntimeLifecycleState.READY)
    return tracker


def test_initial_snapshot_is_not_operationally_ready() -> None:
    snapshot = OperationalStatusTracker().snapshot(observed_at=NOW)

    assert snapshot.lifecycle_state is RuntimeLifecycleState.STARTING
    assert snapshot.liveness
    assert not snapshot.operational_ready
    assert not snapshot.accepting_new_execution
    assert snapshot.readiness_reasons == (
        OperationalReadinessReason.NOT_REGISTERED,
        OperationalReadinessReason.STARTUP_RECOVERY_PENDING,
        OperationalReadinessReason.RUNTIME_STARTING,
    )


def test_ready_and_execution_availability_are_distinct() -> None:
    tracker = ready_tracker()

    idle = tracker.snapshot(observed_at=NOW)
    assert idle.operational_ready
    assert idle.accepting_new_execution
    assert idle.last_server_success_at == NOW
    assert idle.last_heartbeat_success_at is None

    tracker.set_active_execution(EXECUTION_ID)
    active = tracker.snapshot(observed_at=NOW)
    assert active.operational_ready
    assert not active.accepting_new_execution
    assert active.active_execution_id == EXECUTION_ID

    tracker.set_active_execution(None)
    assert tracker.snapshot(observed_at=NOW).accepting_new_execution


def test_ready_heartbeat_only_runtime_is_not_available_for_execution() -> None:
    tracker = OperationalStatusTracker()
    tracker.mark_registered(AGENT_ID, ROBOT_ID, at=NOW)
    tracker.mark_recovery_complete()
    tracker.set_lifecycle(RuntimeLifecycleState.READY)

    snapshot = tracker.snapshot(observed_at=NOW)
    assert snapshot.operational_ready
    assert not snapshot.accepting_new_execution


def test_degraded_and_stopping_states_fail_closed() -> None:
    tracker = ready_tracker()
    tracker.set_connectivity(RuntimeConnectivityState.DEGRADED)
    tracker.set_lifecycle(RuntimeLifecycleState.DEGRADED)
    degraded = tracker.snapshot(observed_at=NOW)
    assert not degraded.operational_ready
    assert not degraded.accepting_new_execution
    assert OperationalReadinessReason.SERVER_CONNECTIVITY_DEGRADED in degraded.readiness_reasons

    tracker.set_lifecycle(RuntimeLifecycleState.STOPPING)
    stopping = tracker.snapshot(observed_at=NOW)
    assert stopping.liveness
    assert not stopping.operational_ready
    assert OperationalReadinessReason.RUNTIME_STOPPING in stopping.readiness_reasons

    tracker.set_lifecycle(RuntimeLifecycleState.STOPPED)
    stopped = tracker.snapshot(observed_at=NOW)
    assert not stopped.liveness
    assert not stopped.operational_ready


def test_server_success_timestamps_only_change_on_success() -> None:
    tracker = ready_tracker()
    tracker.mark_server_success(heartbeat=True, at=NOW)
    snapshot = tracker.snapshot(observed_at=NOW)
    assert snapshot.last_server_success_at == NOW
    assert snapshot.last_heartbeat_success_at == NOW


def test_snapshot_json_is_stable_and_secret_free() -> None:
    payload = ready_tracker().snapshot(observed_at=NOW).to_dict()

    assert payload["schemaVersion"] == 3
    assert payload["lifecycleState"] == "READY"
    assert payload["connectivityState"] == "CONNECTED"
    serialized = str(payload)
    for secret in ("agentToken", "Authorization", "commandPayload", "sessionToken"):
        assert secret not in serialized


def test_status_exposes_fail_closed_physical_readiness_without_secrets() -> None:
    payload = OperationalStatusTracker().snapshot(observed_at=NOW).to_dict()

    assert payload["physicalExecutionEnabled"] is False
    assert payload["physicalReadiness"]["ready"] is False
    assert "PHYSICAL_EXECUTION_DISABLED" in payload["physicalReadiness"]["blockers"]
    assert payload["physicalReadiness"]["telemetryFresh"] is None
    assert payload["physicalReadiness"]["batterySufficient"] is None
    assert payload["physicalReadiness"]["capabilityVerified"] is None
    assert "token" not in str(payload).lower()


def test_status_publisher_writes_atomic_json_and_clears(tmp_path) -> None:
    path = tmp_path / "runtime" / "status.json"
    publisher = StatusSnapshotPublisher(path)
    publisher.publish(ready_tracker().snapshot(observed_at=NOW))

    payload = loads(path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 3
    assert payload["agentId"] == str(AGENT_ID)
    assert not list(path.parent.glob("*.tmp"))

    publisher.clear()
    assert not path.exists()


def test_local_telemetry_evidence_is_utc_safe_and_secret_free() -> None:
    payload = LocalTelemetryEvidence(
        received_at=NOW,
        battery_percent=72,
        fresh=True,
    ).to_dict()

    assert payload == {
        "receivedAt": "2026-09-17T00:00:00+00:00",
        "batteryPercent": 72,
        "fresh": True,
    }
    assert "token" not in str(payload).lower()


@pytest.mark.parametrize("battery", [True, -1, 101, 1.5])
def test_local_telemetry_evidence_rejects_invalid_battery(battery: object) -> None:
    with pytest.raises(ValueError, match="battery_percent"):
        LocalTelemetryEvidence(received_at=NOW, battery_percent=battery, fresh=True)  # type: ignore[arg-type]


def test_status_publisher_failure_is_observable_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog
) -> None:
    publisher = StatusSnapshotPublisher(tmp_path / "status.json")
    monkeypatch.setattr(
        "poppy_agent.operational_status.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("write failed")),
    )

    with caplog.at_level("ERROR"):
        publisher.publish(ready_tracker().snapshot(observed_at=NOW))

    assert "operational_status_publish_failed" in caplog.text


def test_snapshot_copy_is_thread_safe() -> None:
    tracker = ready_tracker()

    with ThreadPoolExecutor(max_workers=4) as workers:
        snapshots = list(workers.map(lambda _: tracker.snapshot(observed_at=NOW), range(100)))

    assert len(snapshots) == 100
    assert all(snapshot.operational_ready for snapshot in snapshots)
