"""scripts/ops_laptop_check.py against a fixture filesystem and fake queries (#103)."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ops_laptop_check", ROOT / "scripts" / "ops_laptop_check.py"
)
assert SPEC is not None and SPEC.loader is not None
check = importlib.util.module_from_spec(SPEC)
sys.modules["ops_laptop_check"] = check
SPEC.loader.exec_module(check)

XRANDR_OK = """Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal) 344mm x 194mm
   1920x1080     60.02*+  48.00
HDMI-1 connected 1920x1080+0+0 (normal) 531mm x 299mm
   1920x1080     60.00*+  50.00    59.94
   1280x720      60.00
DP-1 disconnected (normal left inverted right x axis y axis)
"""
GOOD_GSETTINGS = {
    "sleep-inactive-ac-type": "'nothing'\n",
    "sleep-inactive-battery-type": "'nothing'\n",
    "idle-delay": "uint32 0\n",
}


def fake(xrandr: str | None = XRANDR_OK, gsettings: dict[str, str] | None = None):
    values = GOOD_GSETTINGS if gsettings is None else gsettings

    def runner(command: Sequence[str]) -> str | None:
        if command[0] == "xrandr":
            return xrandr
        if command[0] == "gsettings":
            return values.get(command[3])
        raise AssertionError(f"unexpected command {command}")

    return runner


def good_root(tmp_path: Path) -> Path:
    (tmp_path / "etc/gdm3").mkdir(parents=True)
    (tmp_path / "etc/gdm3/custom.conf").write_text(
        "[daemon]\n#WaylandEnable=true\nWaylandEnable=false\n", encoding="utf-8"
    )
    (tmp_path / "etc/systemd/logind.conf.d").mkdir(parents=True)
    (tmp_path / "etc/systemd/logind.conf").write_text(
        "[Login]\n#HandleLidSwitch=suspend\n", encoding="utf-8"
    )
    (tmp_path / "etc/systemd/logind.conf.d/50-poppy-lid.conf").write_text(
        "[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\n"
        "HandleLidSwitchDocked=ignore\n",
        encoding="utf-8",
    )
    system = tmp_path / "etc/systemd/system"
    system.mkdir(parents=True)
    for target in check.SLEEP_TARGETS:
        os.symlink("/dev/null", system / target)
    return tmp_path


def test_all_persistent_settings_pass(tmp_path: Path) -> None:
    checks = check.run_checks(good_root(tmp_path), fake())
    assert [c.result for c in checks] == ["PASS"] * 5
    assert check.summary(checks) == "OK: 화면·전원 설정 유지됨"
    assert "HDMI-1 1920x1080@60.00" in checks[-1].detail


def test_wayland_lid_and_sleep_failures(tmp_path: Path) -> None:
    root = good_root(tmp_path)
    (root / "etc/gdm3/custom.conf").write_text("[daemon]\nWaylandEnable=true\n", encoding="utf-8")
    (root / "etc/systemd/logind.conf.d/90-later.conf").write_text(
        "[Login]\nHandleLidSwitch=suspend\n", encoding="utf-8"
    )
    (root / "etc/systemd/system/suspend.target").unlink()
    checks = {c.name: c for c in check.run_checks(root, fake())}

    assert checks["Xorg 기본 세션"].result == "FAIL"
    assert "HandleLidSwitch=suspend" in checks["덮개 닫힘 무시"].detail
    assert "suspend.target" in checks["절전 target mask"].detail
    assert check.summary(list(checks.values())).startswith("FAIL: ")


def test_missing_files_fail_instead_of_passing(tmp_path: Path) -> None:
    checks = check.run_checks(tmp_path, fake())
    assert [c.result for c in checks[:3]] == ["FAIL", "FAIL", "FAIL"]


def test_gnome_values_and_unavailable_session(tmp_path: Path) -> None:
    root = good_root(tmp_path)
    wrong = {**GOOD_GSETTINGS, "idle-delay": "uint32 300\n"}
    assert check.check_gnome(fake(gsettings=wrong)).detail == "idle-delay=uint32 300"
    assert check.check_gnome(fake(gsettings={})).result == "UNKNOWN"
    checks = check.run_checks(root, fake(xrandr=None, gsettings={}))
    assert check.summary(checks).startswith("CHECK: ")


def test_display_requires_external_1080p60() -> None:
    laptop_only = XRANDR_OK.split("HDMI-1")[0]
    assert check.check_display(fake(xrandr=laptop_only)).detail == "외부 모니터 없음"
    at_50 = XRANDR_OK.replace("60.00*+  50.00", "60.00 +  50.00*")
    result = check.check_display(fake(xrandr=at_50))
    assert result.result == "FAIL" and "HDMI-1 1920x1080@50.00" in result.detail
    assert check.check_display(fake(xrandr=None)).result == "UNKNOWN"


def test_script_has_no_mutating_commands() -> None:
    source = (ROOT / "scripts/ops_laptop_check.py").read_text(encoding="utf-8")
    for forbidden in ("sudo", "systemctl", "gsettings set", "--output", "write_text"):
        assert forbidden not in source
