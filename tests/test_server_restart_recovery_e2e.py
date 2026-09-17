import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import server_restart_recovery_e2e as rehearsal  # noqa: E402


def test_command_json_requires_non_empty_string_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPY_SERVER_RESTART_COMMAND_JSON", json.dumps(["java", "-jar"]))
    monkeypatch.delenv("POPPY_SERVER_RESTART_COMMAND", raising=False)

    assert rehearsal._command_from_environment() == ["java", "-jar"]


def test_command_json_rejects_non_string_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPY_SERVER_RESTART_COMMAND_JSON", json.dumps(["java", 42]))
    monkeypatch.delenv("POPPY_SERVER_RESTART_COMMAND", raising=False)

    with pytest.raises(rehearsal.ServerRestartRehearsalError, match="string array"):
        rehearsal._command_from_environment()


def test_environment_requires_explicit_mock_process_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POPPY_SERVER_RESTART_REHEARSAL", raising=False)
    monkeypatch.setenv("ROBOT_MODE", "mock")
    monkeypatch.setenv("POPPY_E2E_SERVER_URL", "http://localhost:18080")
    monkeypatch.setenv("POPPY_E2E_AGENT_TOKEN", "test-token")
    monkeypatch.setenv("POPPY_SERVER_RESTART_COMMAND_JSON", json.dumps(["java", "-version"]))

    with pytest.raises(rehearsal.ServerRestartRehearsalError, match="REHEARSAL=1"):
        rehearsal._validate_environment()


def test_environment_rejects_unitree_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPY_SERVER_RESTART_REHEARSAL", "1")
    monkeypatch.setenv("ROBOT_MODE", "unitree")
    monkeypatch.setenv("POPPY_E2E_SERVER_URL", "http://localhost:18080")
    monkeypatch.setenv("POPPY_E2E_AGENT_TOKEN", "test-token")
    monkeypatch.setenv("POPPY_SERVER_RESTART_COMMAND_JSON", json.dumps(["java", "-version"]))

    with pytest.raises(rehearsal.ServerRestartRehearsalError, match="ROBOT_MODE=mock"):
        rehearsal._validate_environment()


def test_harness_does_not_reset_database_or_target_host_network() -> None:
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")

    assert "DROP DATABASE" not in source
    assert "docker compose down" not in source
    assert "netsh" not in source.lower()
    assert "POPPY_SERVER_RESTART_REHEARSAL" in source
    assert "process.terminate()" in source
    assert "process.kill()" in source
