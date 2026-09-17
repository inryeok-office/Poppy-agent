from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

cleanup = importlib.import_module("rehearsal_cleanup")
systemd = importlib.import_module("systemd_recovery_rehearsal")


def test_cleanup_runs_all_steps_and_reports_failures_without_stopping() -> None:
    calls: list[str] = []

    def fail() -> None:
        calls.append("first")
        raise RuntimeError("primary-like cleanup failure")

    def succeed() -> None:
        calls.append("second")

    failures = cleanup.run_cleanup_steps([("first cleanup", fail), ("second cleanup", succeed)])

    assert calls == ["first", "second"]
    assert failures == ["first cleanup: RuntimeError"]


def test_existing_service_user_is_not_marked_for_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        systemd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(systemd, "_command", lambda *args, **kwargs: commands.append(args))

    assert systemd._ensure_service_user() is False
    assert commands == []


def test_systemd_cleanup_removes_unit_before_reload_and_keeps_existing_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unit_path = tmp_path / "rehearsal.service"
    unit_path.write_text("unit", encoding="utf-8")
    events: list[str] = []

    monkeypatch.setattr(systemd, "UNIT_PATH", unit_path)
    monkeypatch.setattr(
        systemd,
        "_systemctl",
        lambda *args, **kwargs: events.append("systemctl " + " ".join(args)),
    )
    monkeypatch.setattr(systemd, "_command", lambda *args, **kwargs: events.append("command"))

    failures = systemd._cleanup_unit(systemd.RehearsalResources(unit_created=True))

    assert failures == []
    assert not unit_path.exists()
    assert events == [
        "systemctl disable --now poppy-agent-rehearsal.service",
        "systemctl daemon-reload",
    ]


def test_systemd_cleanup_does_not_touch_unowned_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        systemd,
        "_systemctl",
        lambda *args, **kwargs: pytest.fail("unowned systemd unit was touched"),
    )

    assert systemd._cleanup_unit(systemd.RehearsalResources()) == []
