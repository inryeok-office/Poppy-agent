"""Execution failure codes (#101), fakes only."""

from __future__ import annotations

import logging

import pytest

from poppy_agent.command import Posture
from poppy_agent.execution import ExecutionStatus, FailureCode
from poppy_agent.execution.failure import CodedError, failure_code_of
from poppy_agent.hardware.unitree_sdk import MotionStreamTiming
from test_controlled_motion_open import (
    EXPIRES,
    FakeClock,
    FakeSportClient,
    build,
    move,
    posture,
    run,
)


class RejectingSportClient(FakeSportClient):
    def __init__(self, clock: FakeClock, reject: str) -> None:
        super().__init__(clock)
        self.reject = reject

    def _record(self, name: str, *args: float) -> int:
        self.calls.append((name, args))
        return 3104 if name == self.reject else 0


def test_codes_are_the_issue_contract_values() -> None:
    assert {code.value for code in FailureCode} == {
        "SAFETY_REJECTED",
        "APPROVAL_EXPIRED",
        "TELEMETRY_STALE",
        "POSTURE_UNKNOWN",
        "SDK_REJECTED",
        "TIMEOUT",
        "NOT_MOVED",
        "EXECUTION_ERROR",
    }


def test_cause_chain_lookup_and_default() -> None:
    inner = CodedError("inner", failure_code=FailureCode.SDK_REJECTED)
    try:
        try:
            raise inner
        except CodedError as exc:
            raise RuntimeError("wrapped") from exc
    except RuntimeError as outer:
        assert failure_code_of(outer, FailureCode.EXECUTION_ERROR) is FailureCode.SDK_REJECTED
    assert failure_code_of(ValueError("x"), FailureCode.TIMEOUT) is FailureCode.TIMEOUT
    assert failure_code_of(None, FailureCode.TIMEOUT) is FailureCode.TIMEOUT


def test_completed_execution_has_no_code() -> None:
    clock = FakeClock()
    result = run(build(clock, FakeSportClient(clock)), move(0.5))
    assert result.status is ExecutionStatus.COMPLETED
    assert result.failure_code is None


def test_guard_limit_is_safety_rejected() -> None:
    clock = FakeClock()
    result = run(build(clock, FakeSportClient(clock)), move(3.5))
    assert result.failure_code is FailureCode.SAFETY_REJECTED


def test_expired_approval_code() -> None:
    clock = FakeClock()
    trial = build(clock, FakeSportClient(clock))
    clock.wall = EXPIRES
    assert run(trial, move(0.5)).failure_code is FailureCode.APPROVAL_EXPIRED


def test_stale_telemetry_code() -> None:
    clock = FakeClock()
    result = run(build(clock, FakeSportClient(clock), telemetry_fresh=False), move(0.5))
    assert result.failure_code is FailureCode.TELEMETRY_STALE


@pytest.mark.parametrize(
    ("reject", "commands"),
    [
        ("Sit", (posture(Posture.SIT),)),
        ("Move", (move(0.5),)),
    ],
)
def test_sdk_rejection_code_without_sdk_details(reject: str, commands: tuple) -> None:
    clock = FakeClock()
    result = run(build(clock, RejectingSportClient(clock, reject)), *commands)
    assert result.status is ExecutionStatus.FAILED
    assert result.failure_code is FailureCode.SDK_REJECTED


def test_blocked_move_call_is_timeout() -> None:
    clock = FakeClock()

    class SlowSportClient(FakeSportClient):
        def Move(self, vx: float, vy: float, vyaw: float) -> int:
            clock.advance(1.0)
            return super().Move(vx, vy, vyaw)

    sport = SlowSportClient(clock)
    trial = build(clock, sport)
    timing = MotionStreamTiming(monotonic=clock.monotonic, sleep=clock.sleep, wait=clock.wait)
    assert timing.max_move_call_seconds < 1.0
    assert run(trial, move(0.5)).failure_code is FailureCode.TIMEOUT


def test_transport_exception_is_execution_error() -> None:
    clock = FakeClock()
    sport = FakeSportClient(clock, move_error_at=0)
    assert run(build(clock, sport), move(0.5)).failure_code is FailureCode.EXECUTION_ERROR


def test_failure_code_is_an_allowed_log_field(caplog: pytest.LogCaptureFixture) -> None:
    from poppy_agent.observability import log_event

    with caplog.at_level(logging.ERROR):
        log_event(
            logging.getLogger("test"), logging.ERROR, "execution_failed", failure_code="TIMEOUT"
        )
    assert caplog.records[-1].poppy_context == {"failure_code": "TIMEOUT"}  # type: ignore[attr-defined]
