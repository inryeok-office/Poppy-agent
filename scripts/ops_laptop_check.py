"""Read-only check of the operator laptop's persistent display and power settings (#103).

Checks: Xorg default session (GDM ``WaylandEnable=false``), logind lid switch
``ignore``, sleep targets masked, GNOME automatic suspend/idle off, and an
external 1920x1080 at 60 Hz mode.  Nothing is changed; each failed item prints
the persistent fix from docs/ops-laptop.md.  The last line is a one-line summary.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
LID_KEYS = ("HandleLidSwitch", "HandleLidSwitchExternalPower", "HandleLidSwitchDocked")
SLEEP_TARGETS = ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target")
GSETTINGS = (
    ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "'nothing'"),
    ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type", "'nothing'"),
    ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
)

Runner = Callable[[Sequence[str]], str | None]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    result: str
    detail: str


def run_readonly(command: Sequence[str]) -> str | None:
    """Run a read-only query; ``None`` when it is unavailable or fails."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed read-only queries
            list(command), capture_output=True, text=True, check=False, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _ini_value(paths: Sequence[Path], key: str) -> str | None:
    """Last uncommented ``key=value`` across files in order (later files win)."""
    value: str | None = None
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", ";")):
                continue
            name, sep, raw = stripped.partition("=")
            if sep and name.strip() == key:
                value = raw.strip()
    return value


def check_xorg(root: Path) -> Check:
    value = _ini_value([root / "etc/gdm3/custom.conf"], "WaylandEnable")
    if value is None:
        return Check("Xorg 기본 세션", FAIL, "/etc/gdm3/custom.conf 에 WaylandEnable=false 없음")
    if value.lower() == "false":
        return Check("Xorg 기본 세션", PASS, "WaylandEnable=false")
    return Check("Xorg 기본 세션", FAIL, f"WaylandEnable={value}")


def check_lid(root: Path) -> Check:
    drop_ins = sorted((root / "etc/systemd/logind.conf.d").glob("*.conf"))
    paths = [root / "etc/systemd/logind.conf", *drop_ins]
    wrong = [
        f"{key}={_ini_value(paths, key)}" for key in LID_KEYS if _ini_value(paths, key) != "ignore"
    ]
    if wrong:
        return Check("덮개 닫힘 무시", FAIL, ", ".join(wrong))
    return Check("덮개 닫힘 무시", PASS, "HandleLidSwitch*=ignore")


def check_sleep_masked(root: Path) -> Check:
    unmasked = []
    for target in SLEEP_TARGETS:
        path = root / "etc/systemd/system" / target
        try:
            masked = path.is_symlink() and os.readlink(path) == "/dev/null"
        except OSError:
            masked = False
        if not masked:
            unmasked.append(target)
    if unmasked:
        return Check("절전 target mask", FAIL, "mask 안 됨: " + ", ".join(unmasked))
    return Check("절전 target mask", PASS, "sleep/suspend/hibernate/hybrid-sleep masked")


def check_gnome(runner: Runner) -> Check:
    wrong = []
    for schema, key, expected in GSETTINGS:
        value = runner(["gsettings", "get", schema, key])
        if value is None:
            return Check(
                "GNOME 자동 절전·화면 끄기", UNKNOWN, "gsettings 조회 불가(그래픽 세션 밖)"
            )
        if value.strip() != expected:
            wrong.append(f"{key}={value.strip()}")
    if wrong:
        return Check("GNOME 자동 절전·화면 끄기", FAIL, ", ".join(wrong))
    return Check("GNOME 자동 절전·화면 끄기", PASS, "자동 절전 nothing, idle-delay 0")


_OUTPUT = re.compile(r"^(\S+) connected")
_MODE = re.compile(r"^\s+(\d+x\d+)\s+(.*)$")


def check_display(runner: Runner) -> Check:
    text = runner(["xrandr", "--current"])
    if text is None:
        return Check("외부 모니터 1080p60", UNKNOWN, "xrandr 조회 불가(DISPLAY 없음)")
    output: str | None = None
    current: dict[str, str] = {}
    for line in text.splitlines():
        connected = _OUTPUT.match(line)
        if connected:
            output = connected.group(1)
            continue
        if line and not line[0].isspace():
            output = None
            continue
        mode = _MODE.match(line)
        if output and mode:
            active = [rate for rate in mode.group(2).split() if "*" in rate]
            if active:
                current[output] = f"{mode.group(1)}@{active[0].strip('*+')}"
    external = {name: mode for name, mode in current.items() if not name.startswith("eDP")}
    for name, active_mode in external.items():
        resolution, rate = active_mode.split("@")
        if resolution == "1920x1080" and abs(float(rate) - 60.0) < 0.5:
            return Check("외부 모니터 1080p60", PASS, f"{name} {active_mode}")
    if not external:
        return Check("외부 모니터 1080p60", FAIL, "외부 모니터 없음")
    return Check(
        "외부 모니터 1080p60",
        FAIL,
        ", ".join(f"{name} {mode}" for name, mode in external.items()),
    )


def run_checks(root: Path, runner: Runner) -> list[Check]:
    return [
        check_xorg(root),
        check_lid(root),
        check_sleep_masked(root),
        check_gnome(runner),
        check_display(runner),
    ]


def summary(checks: Sequence[Check]) -> str:
    failed = [c.name for c in checks if c.result == FAIL]
    unknown = [c.name for c in checks if c.result == UNKNOWN]
    if failed:
        return "FAIL: " + ", ".join(failed) + " (docs/ops-laptop.md 참고)"
    if unknown:
        return "CHECK: 그래픽 세션에서 다시 확인 — " + ", ".join(unknown)
    return "OK: 화면·전원 설정 유지됨"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"), help="filesystem root (tests)")
    args = parser.parse_args(argv)
    checks = run_checks(args.root, run_readonly)
    for check in checks:
        print(f"[{check.result}] {check.name}: {check.detail}")
    line = summary(checks)
    print(line)
    return 1 if line.startswith("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
