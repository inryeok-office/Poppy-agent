from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from physical_execution_preflight import run_preflight  # noqa: E402


def test_software_only_physical_execution_preflight() -> None:
    phases = run_preflight(emit=False)

    assert len(phases) == 13
    assert phases[0].name == "default readiness is blocked"
    assert phases[-1].name == "disable is a rollback boundary"
    assert "factory=1" in phases[2].details


def test_preflight_does_not_import_real_unitree_sdk() -> None:
    assert not any(
        name == "unitree_sdk2py" or name.startswith("unitree_sdk2py.") for name in sys.modules
    )
