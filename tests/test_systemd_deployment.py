from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "deploy" / "systemd" / "poppy-agent.service"
ENVIRONMENT_EXAMPLE = ROOT / "deploy" / "systemd" / "poppy-agent.env.example"


def test_systemd_service_uses_runtime_contract() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "User=poppy" in service
    assert "WorkingDirectory=/home/poppy/projects/Poppy-agent" in service
    assert (
        "ExecStart=/home/poppy/projects/Poppy-agent/.venv/bin/python -m poppy_agent.main" in service
    )
    assert "EnvironmentFile=/etc/poppy-agent/poppy-agent.env" in service
    assert "Wants=network-online.target" in service
    assert "After=network-online.target" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=5" in service


def test_systemd_environment_example_has_no_shell_expansion_or_real_secret() -> None:
    environment = ENVIRONMENT_EXAMPLE.read_text(encoding="utf-8")

    assert "POPPY_AGENT_TOKEN=replace-with-agent-token" in environment
    assert "$HOME" not in environment
    assert "${" not in environment
