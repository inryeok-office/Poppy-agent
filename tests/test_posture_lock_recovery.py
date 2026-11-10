"""Posture lock after a rejected SIT/STAND/PRESET and its recovery (#98), fakes only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import poppy_agent.main as main_module
from poppy_agent.command import Posture
from poppy_agent.execution import ExecutionStatus, FailureCode
from poppy_agent.execution.open_motion import (
    OpenMotionGuard,
    OpenMotionGuardError,
    OpenMotionGuardState,
    TrackedPosture,
)
from poppy_agent.hardware import OpenMotionExecution, create_open_motion_executor
from poppy_agent.hardware.unitree_sdk import MotionStreamTiming
from test_controlled_motion_open import (
    EXPIRES,
    OPEN_ENV,
    ROBOT_ID,
    START,
    FakeAdapter,
    FakeClock,
    FakeRuntime,
    FakeSportClient,
    build,
    move,
    open_settings,
    posture,
    preset,
    run,
    task,
    turn,
    unitree_config,
    wait,
)


class RejectingSportClient(FakeSportClient):
    """SDK double that returns a non-zero code for the named operations."""

    def __init__(self, clock: FakeClock, *, reject: set[str]) -> None:
        super().__init__(clock)
        self.reject = reject

    def _record(self, name: str, *args: float) -> int:
        self.calls.append((name, args))
        return 3104 if name in self.reject else 0


class Probe:
    """Read-only posture source double; ``None`` means no fresh answer."""

    def __init__(self, value: Posture | None) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> Posture | None:
        self.calls += 1
        return self.value


def build_with(
    clock: FakeClock, sport: FakeSportClient, probe: Probe | None
) -> OpenMotionExecution:
    return create_open_motion_executor(
        robot_id=ROBOT_ID,
        physical_execution_enabled=True,
        settings=open_settings(),
        telemetry_fresh=lambda: True,
        sport_client_factory=lambda: sport,
        timing=MotionStreamTiming(monotonic=clock.monotonic, sleep=clock.sleep, wait=clock.wait),
        now=clock.wall_now,
        posture_probe=probe,
    )


# --- reproduction of the 10/31 and 11/1 lock ----------------------------------


def test_rejected_sit_no_longer_leaves_a_false_sitting_lock() -> None:
    """Before #98: Sit rejected -> sitting=True -> HELLO blocked, STAND sent RiseSit."""
    clock = FakeClock()
    sport = RejectingSportClient(clock, reject={"Sit"})
    trial = build(clock, sport)

    failed = run(trial, posture(Posture.SIT))
    assert failed.status is ExecutionStatus.FAILED
    assert trial.guard.sitting() is False
    assert trial.guard.posture() is TrackedPosture.UNKNOWN
    assert trial.guard.snapshot()["posture"] == "UNKNOWN"

    sport.calls.clear()
    for program in ((preset("HELLO"),), (posture(Posture.STAND),), (move(0.5),)):
        blocked = run(trial, *program)
        assert blocked.status is ExecutionStatus.FAILED
        assert "posture is unknown" in (blocked.failure_reason or "")
        assert blocked.failure_code is FailureCode.POSTURE_UNKNOWN
    # Nothing reached the SDK while the posture was unknown: no blind RiseSit.
    assert sport.names() == []
    assert trial.guard.available() is False
    assert trial.guard.state() is OpenMotionGuardState.POSTURE_UNKNOWN


@pytest.mark.parametrize(
    ("reject", "program"),
    [
        ({"Sit"}, (posture(Posture.SIT),)),
        ({"RiseSit"}, (posture(Posture.SIT), posture(Posture.STAND))),
        ({"StandUp"}, (posture(Posture.STAND),)),
        ({"BalanceStand"}, (posture(Posture.STAND),)),
        ({"Hello"}, (preset("HELLO"),)),
    ],
)
def test_every_rejected_posture_or_preset_makes_posture_unknown(
    reject: set[str], program: tuple
) -> None:
    clock = FakeClock()
    sport = RejectingSportClient(clock, reject=reject)
    trial = build(clock, sport)

    assert run(trial, *program).status is ExecutionStatus.FAILED
    assert trial.guard.posture() is TrackedPosture.UNKNOWN
    assert trial.guard.snapshot()["lastFailure"] is not None


def test_failed_move_does_not_touch_posture() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, move_error_at=3)
    trial = build(clock, sport)

    assert run(trial, move(0.5)).status is ExecutionStatus.FAILED
    assert trial.guard.posture() is TrackedPosture.STANDING
    assert trial.guard.available() is True


def test_cancelled_stand_makes_posture_unknown() -> None:
    clock = FakeClock(cancel_after_waits=2)
    sport = FakeSportClient(clock)
    trial = build(clock, sport)

    result = run(trial, posture(Posture.SIT), posture(Posture.STAND))
    assert result.status is ExecutionStatus.CANCELLED
    assert sport.names() == ["Sit", "RiseSit"]
    assert trial.guard.posture() is TrackedPosture.UNKNOWN


# --- recovery from the actual posture -----------------------------------------


@pytest.mark.parametrize(
    ("observed", "tracked", "next_ops"),
    [
        (Posture.STAND, TrackedPosture.STANDING, ["Hello", "BalanceStand"]),
        (Posture.SIT, TrackedPosture.SITTING, ["RiseSit"]),
    ],
)
def test_rejected_sit_resyncs_from_the_observed_posture(
    observed: Posture, tracked: TrackedPosture, next_ops: list[str]
) -> None:
    clock = FakeClock()
    sport = RejectingSportClient(clock, reject={"Sit"})
    probe = Probe(observed)
    trial = build_with(clock, sport, probe)

    assert run(trial, posture(Posture.SIT)).status is ExecutionStatus.FAILED
    assert trial.guard.posture() is tracked
    assert trial.guard.available() is True

    sport.calls.clear()
    sport.reject = set()
    follow_up = preset("HELLO") if observed is Posture.STAND else posture(Posture.STAND)
    assert run(trial, follow_up).status is ExecutionStatus.COMPLETED
    assert sport.names() == next_ops


def test_unknown_posture_clears_only_when_the_robot_answers() -> None:
    clock = FakeClock()
    sport = RejectingSportClient(clock, reject={"Hello"})
    probe = Probe(Posture.STAND)
    trial = build_with(clock, sport, probe)
    probe.value = None

    assert run(trial, preset("HELLO")).status is ExecutionStatus.FAILED
    assert trial.guard.state() is OpenMotionGuardState.POSTURE_UNKNOWN
    assert run(trial, move(0.5)).status is ExecutionStatus.FAILED

    probe.value = Posture.STAND
    assert trial.guard.state() is OpenMotionGuardState.AVAILABLE
    assert trial.guard.snapshot()["postureUnknownReason"] is None
    assert run(trial, move(0.5)).status is ExecutionStatus.COMPLETED


def test_probe_errors_count_as_no_answer() -> None:
    def broken() -> Posture | None:
        raise RuntimeError("stale sport state")

    guard = OpenMotionGuard(
        open_settings(), telemetry_fresh=lambda: True, now=lambda: START, posture_probe=broken
    )
    assert guard.posture() is TrackedPosture.UNKNOWN
    with pytest.raises(OpenMotionGuardError, match="posture is unknown"):
        guard.admit(task(turn(90)).command_program)


def test_probe_sets_the_initial_posture() -> None:
    guard = OpenMotionGuard(
        open_settings(),
        telemetry_fresh=lambda: True,
        now=lambda: START,
        posture_probe=Probe(Posture.SIT),
    )
    assert guard.sitting() is True
    with pytest.raises(OpenMotionGuardError, match="after SIT"):
        guard.admit(task(move(0.5)).command_program)


def test_without_probe_operator_resync_keeps_the_lock() -> None:
    guard = OpenMotionGuard(open_settings(), telemetry_fresh=lambda: True, now=lambda: START)
    guard.mark_posture_unknown("SIT outcome unknown: UnitreeCommandBackendError")
    assert guard.resync_posture() is TrackedPosture.UNKNOWN
    assert guard.state() is OpenMotionGuardState.POSTURE_UNKNOWN


def test_wait_only_program_is_still_admitted_with_unknown_posture() -> None:
    guard = OpenMotionGuard(open_settings(), telemetry_fresh=lambda: True, now=lambda: START)
    guard.mark_posture_unknown("test")
    guard.admit(task(wait(1)).command_program)


# --- main wiring ---------------------------------------------------------------


class ProbingAdapter(FakeAdapter):
    def __init__(self, probe: Probe) -> None:
        super().__init__()
        self.observed_posture = probe


def test_main_wires_observed_posture_and_reports_posture_unknown(monkeypatch) -> None:
    clock = FakeClock()
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> OpenMotionExecution:
        captured.update(kwargs)
        guard = OpenMotionGuard(
            open_settings(),
            telemetry_fresh=lambda: True,
            now=clock.wall_now,
            posture_probe=kwargs["posture_probe"],  # type: ignore[arg-type]
        )
        return OpenMotionExecution(object(), guard)  # type: ignore[arg-type]

    monkeypatch.setattr(main_module, "create_open_motion_executor", factory)
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    config = unitree_config(
        enabled=True, trial={**OPEN_ENV, "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": expires}
    )
    probe = Probe(None)
    adapter, runtime = ProbingAdapter(probe), FakeRuntime()

    main_module._create_physical_trial_executor(
        config,
        SimpleNamespace(adapter=adapter),  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert captured["posture_probe"] is probe
    status = runtime.physical_status()
    assert status["state"] == "NOT_READY"
    assert status["reasons"] == ["POSTURE_UNKNOWN"]
    assert adapter.readiness() is False

    probe.value = Posture.STAND
    status = runtime.physical_status()
    assert status["state"] == "READY"
    assert status["reasons"] == []
    assert status["trial"]["posture"] == "STANDING"
    assert clock.wall < EXPIRES


def test_main_without_observed_posture_passes_no_probe(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> OpenMotionExecution:
        captured.update(kwargs)
        guard = OpenMotionGuard(open_settings(), telemetry_fresh=lambda: True, now=lambda: START)
        return OpenMotionExecution(object(), guard)  # type: ignore[arg-type]

    monkeypatch.setattr(main_module, "create_open_motion_executor", factory)
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    config = unitree_config(
        enabled=True, trial={**OPEN_ENV, "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": expires}
    )
    main_module._create_physical_trial_executor(
        config,
        SimpleNamespace(adapter=FakeAdapter()),  # type: ignore[arg-type]
        FakeRuntime(),  # type: ignore[arg-type]
    )
    assert captured["posture_probe"] is None
