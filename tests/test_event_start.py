"""scripts/event_start.py with fake runners and status snapshots only (#100)."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("event_start", ROOT / "scripts" / "event_start.py")
assert SPEC is not None and SPEC.loader is not None
event_start = importlib.util.module_from_spec(SPEC)
sys.modules["event_start"] = event_start
SPEC.loader.exec_module(event_start)

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
SWITCH = ["/operator/switch.sh", "on"]


def snapshot(
    *,
    fresh: bool = True,
    lifecycle: str = "READY",
    physical_state: str = "NOT_READY",
    expires: datetime | None = NOW + timedelta(hours=2),
    reasons: list[str] | None = None,
    issues: list[str] | None = None,
) -> dict[str, object]:
    trial = {} if expires is None else {"expiresAt": expires.isoformat()}
    return {
        "lifecycleState": lifecycle,
        "telemetry": {"fresh": fresh, "batteryPercent": 80, "receivedAt": NOW.isoformat()},
        "physicalExecution": {
            "state": physical_state,
            "reasons": reasons or [],
            "configIssues": issues or [],
            "trial": trial,
        },
    }


class FakeRunner:
    def __init__(self, active_state: str = "failed", drop_in: bool = True) -> None:
        self.active_state = active_state
        self.drop_in = drop_in
        self.commands: list[list[str]] = []
        self.switch_exit = 0
        self.on_switch: list[dict[str, object]] | None = None

    def __call__(self, command: Sequence[str]) -> event_start.CommandResult:
        self.commands.append(list(command))
        if command[:2] == ["systemctl", "show"]:
            return event_start.CommandResult(0, f"ActiveState={self.active_state}\nResult=x\n")
        if command[0] == "cmp":
            return event_start.CommandResult(0 if self.drop_in else 1)
        if list(command) == SWITCH:
            return event_start.CommandResult(self.switch_exit)
        return event_start.CommandResult(0)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def starter(
    runner: FakeRunner,
    statuses: list[dict[str, object] | None],
    *,
    execute: bool = True,
    queue_cleared: bool = True,
    switch: list[str] | None = SWITCH,
) -> event_start.EventStart:
    clock = Clock()
    queue = list(statuses)

    def reader(_path: Path) -> dict[str, object] | None:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return event_start.EventStart(
        runner=runner,
        status_path=Path("/nonexistent/status.json"),
        execute=execute,
        queue_cleared=queue_cleared,
        switch_command=switch,
        wait_seconds=30,
        poll_seconds=5,
        now=lambda: NOW,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        status_reader=reader,
    )


def test_failed_service_is_reset_started_and_switched_on_in_order() -> None:
    runner = FakeRunner("failed")
    summary = starter(runner, [snapshot(), snapshot(physical_state="READY")]).run()

    assert summary == "OK: 실제 동작 READY"
    mutating = [c for c in runner.commands if c[0] != "systemctl" and c[0] != "cmp"]
    assert mutating == [
        ["sudo", "systemctl", "reset-failed", "poppy-agent"],
        ["sudo", "systemctl", "start", "poppy-agent"],
        SWITCH,
    ]


def test_active_service_is_left_alone() -> None:
    runner = FakeRunner("active")
    starter(runner, [snapshot(), snapshot(physical_state="READY")]).run()
    assert not any(c[:2] == ["sudo", "systemctl"] for c in runner.commands)


def test_missing_drop_in_is_installed_and_reloaded() -> None:
    runner = FakeRunner("active", drop_in=False)
    starter(runner, [snapshot(), snapshot(physical_state="READY")]).run()
    install = [c for c in runner.commands if c[:2] == ["sudo", "install"]]
    assert install and install[0][-1].endswith("poppy-agent.service.d/10-event-no-restart.conf")
    assert ["sudo", "systemctl", "daemon-reload"] in runner.commands


def test_late_robot_is_waited_for_then_proceeds() -> None:
    runner = FakeRunner("active")
    stale = snapshot(fresh=False)
    summary = starter(
        runner, [None, stale, stale, snapshot(), snapshot(physical_state="READY")]
    ).run()
    assert summary.startswith("OK")


def test_robot_that_never_appears_fails_before_switch() -> None:
    runner = FakeRunner("active")
    summary = starter(runner, [snapshot(fresh=False)]).run()
    assert summary.startswith("FAIL: 로봇 미기동")
    assert SWITCH not in runner.commands


@pytest.mark.parametrize(
    "status",
    [
        snapshot(reasons=["TRIAL_EXPIRED"]),
        snapshot(issues=["POPPY_PHYSICAL_TRIAL_EXPIRES_AT is not in the future"]),
        snapshot(expires=NOW + timedelta(minutes=10)),
        snapshot(expires=NOW - timedelta(minutes=1)),
    ],
)
def test_expired_or_expiring_approval_stops_before_switch(status: dict[str, object]) -> None:
    runner = FakeRunner("active")
    summary = starter(runner, [status]).run()
    assert summary.startswith("FAIL: 승인")
    assert SWITCH not in runner.commands


def test_unconfirmed_queue_blocks_the_switch() -> None:
    runner = FakeRunner("active")
    summary = starter(runner, [snapshot()], queue_cleared=False).run()
    assert summary.startswith("FAIL: 대기 실행 정리 미확인")
    assert SWITCH not in runner.commands


def test_switch_failure_and_not_ready_are_reported() -> None:
    runner = FakeRunner("active")
    runner.switch_exit = 2
    assert starter(runner, [snapshot()]).run() == "FAIL: 켜기 명령 실패(exit 2)"

    runner = FakeRunner("active")
    summary = starter(runner, [snapshot()]).run()
    assert summary.startswith("FAIL: 켜기 후 READY 아님")


def test_without_switch_command_the_switch_is_manual() -> None:
    runner = FakeRunner("active")
    summary = starter(runner, [snapshot()], switch=None).run()
    assert summary.startswith("MANUAL")


def test_unexpected_service_state_needs_a_human() -> None:
    runner = FakeRunner("deactivating")
    assert starter(runner, [snapshot()]).run() == "FAIL: 서비스 상태 deactivating: 수동 확인 필요"


def test_default_cli_is_a_dry_run_that_executes_nothing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run must not run subprocesses")

    monkeypatch.setattr(event_start.subprocess, "run", forbidden)
    monkeypatch.setattr(event_start.time, "sleep", lambda _s: None)
    status = tmp_path / "status.json"
    future = datetime.now(UTC) + timedelta(hours=2)
    import json

    status.write_text(json.dumps(snapshot(expires=future)), encoding="utf-8")
    code = event_start.main(
        ["--status-path", str(status), "--queue-cleared", "--switch-command", "/op/switch.sh on"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "(dry-run) sudo systemctl reset-failed poppy-agent" in out
    assert "(dry-run) /op/switch.sh on" in out
    assert out.strip().splitlines()[-1] == "DRY-RUN OK: 실제 실행은 --execute"


def test_drop_in_sets_restart_no() -> None:
    text = (ROOT / "deploy/systemd/poppy-agent.service.d/10-event-no-restart.conf").read_text(
        encoding="utf-8"
    )
    assert "[Service]" in text and "Restart=no" in text
