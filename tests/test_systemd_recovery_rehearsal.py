from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "systemd_recovery_rehearsal.py"


def test_systemd_rehearsal_is_explicitly_guarded_and_mock_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'POPPY_SYSTEMD_REHEARSAL") != "1"' in source
    assert 'platform.system() != "Linux"' in source
    assert "os.geteuid() != 0" in source
    assert 'raise RehearsalError("Unitree mode is forbidden")' in source
    assert 'UNIT_NAME = "poppy-agent-rehearsal.service"' in source
    assert "RuntimeDirectory=poppy-agent-rehearsal" in source


def test_systemd_rehearsal_never_targets_the_production_unit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '_systemctl("enable", UNIT_NAME)' in source
    assert '_systemctl("start", UNIT_NAME)' in source
    assert '_systemctl("restart", UNIT_NAME)' in source
    assert '_systemctl("stop", UNIT_NAME)' in source
