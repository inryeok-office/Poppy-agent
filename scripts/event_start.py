"""One-command event start for the operator laptop (#100).

Order: service state -> reset-failed/start (physical execution stays as configured)
-> persistent ``Restart=no`` drop-in -> wait for a late Robot (fresh telemetry)
-> approval expiry check -> stale pending Execution check -> switch on -> READY.
The last line printed is a one-line summary for the operator.

Safety:
- The default is a dry run: every command is printed and nothing is executed.
  ``--execute`` is required to touch systemd or run the switch command.
- The approval expiry is only checked, never extended or bypassed.  An expired or
  soon-expiring approval stops the script before the switch.
- Physical execution is switched on only after the operator confirms the stale
  pending Executions are cleared (``--queue-cleared``; Poppy-Server#132).
- This script sends no Robot command and does not read the EnvironmentFile; it
  reads only the secret-free status snapshot (``POPPY_RUNTIME_STATUS_PATH``).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

UNIT = "poppy-agent"
STATUS_PATH = Path("/run/poppy-agent/status.json")
DROP_IN_NAME = "10-event-no-restart.conf"
DROP_IN_SOURCE = (
    Path(__file__).resolve().parents[1] / "deploy" / "systemd" / "poppy-agent.service.d"
)
DROP_IN_DIR = Path("/etc/systemd/system/poppy-agent.service.d")
MIN_APPROVAL_REMAINING = timedelta(minutes=30)


class StepFailed(RuntimeError):
    """A step that must stop the start sequence; the message is the summary."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""


Runner = Callable[[Sequence[str]], CommandResult]


@dataclass
class Report:
    steps: list[tuple[str, str]] = field(default_factory=list)

    def add(self, step: str, outcome: str) -> None:
        self.steps.append((step, outcome))
        print(f"[{step}] {outcome}", flush=True)


def subprocess_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(  # noqa: S603 - fixed argument lists only
        list(command), capture_output=True, text=True, check=False, timeout=60
    )
    return CommandResult(completed.returncode, completed.stdout)


class DryRunRunner:
    """Print commands instead of running them; answers come from a simulated state."""

    def __init__(self, simulated_active_state: str, drop_in_present: bool) -> None:
        self.active_state = simulated_active_state
        self.drop_in_present = drop_in_present
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> CommandResult:
        self.commands.append(list(command))
        print(f"  (dry-run) {shlex.join(command)}", flush=True)
        if list(command[:2]) == ["systemctl", "show"]:
            return CommandResult(0, f"ActiveState={self.active_state}\n")
        if list(command[:1]) == ["cmp"]:
            return CommandResult(0 if self.drop_in_present else 1)
        if list(command[:3]) in (
            ["sudo", "systemctl", "start"],
            ["sudo", "systemctl", "restart"],
        ):
            self.active_state = "active"
        return CommandResult(0)


def parse_properties(text: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            properties[key.strip()] = value.strip()
    return properties


def read_status(path: Path) -> dict[str, object] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _physical(status: dict[str, object]) -> dict[str, object]:
    physical = status.get("physicalExecution")
    return physical if isinstance(physical, dict) else {}


def telemetry_fresh(status: dict[str, object]) -> bool:
    telemetry = status.get("telemetry")
    return isinstance(telemetry, dict) and telemetry.get("fresh") is True


def approval_expires_at(status: dict[str, object]) -> datetime | None:
    trial = _physical(status).get("trial")
    if not isinstance(trial, dict):
        return None
    raw = trial.get("expiresAt")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def check_approval(status: dict[str, object], now: datetime, minimum: timedelta) -> str:
    """Return a description of the approval window or raise ``StepFailed``."""
    physical = _physical(status)
    reasons = physical.get("reasons")
    issues = physical.get("configIssues")
    if isinstance(reasons, list) and "TRIAL_EXPIRED" in reasons:
        raise StepFailed(
            "승인 만료(TRIAL_EXPIRED): 교사 승인 갱신 후 켜기 스크립트로 새 만료 시각 설정"
        )
    if isinstance(issues, list) and any("EXPIRES_AT" in str(issue) for issue in issues):
        raise StepFailed(
            "승인 만료 시각 설정 오류: 교사 승인 갱신 후 켜기 스크립트로 새 만료 시각 설정"
        )
    expires = approval_expires_at(status)
    if expires is None:
        # Physical execution is still off, so the window is checked by the switch.
        return "만료 시각 미표시(physical off) — 켜기 단계에서 확인"
    remaining = expires - now
    if remaining <= minimum:
        minutes = max(0, int(remaining.total_seconds() // 60))
        raise StepFailed(f"승인 만료 임박(남은 {minutes}분): 교사 승인 갱신 필요")
    return f"승인 유효(남은 {int(remaining.total_seconds() // 60)}분)"


@dataclass
class EventStart:
    runner: Runner
    status_path: Path
    execute: bool
    queue_cleared: bool
    switch_command: list[str] | None
    wait_seconds: float
    poll_seconds: float
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    status_reader: Callable[[Path], dict[str, object] | None] = read_status
    report: Report = field(default_factory=Report)

    def run(self) -> str:
        try:
            self._service()
            self._drop_in()
            status = self._wait_for(
                "로봇 텔레메트리",
                lambda s: s.get("lifecycleState") == "READY" and telemetry_fresh(s),
                "로봇 미기동 또는 텔레메트리 없음: 로봇 전원·유선 연결 확인 후 다시 실행",
            )
            self.report.add("승인", check_approval(status, self.now(), MIN_APPROVAL_REMAINING))
            self._queue()
            self._switch_on()
        except StepFailed as exc:
            return f"FAIL: {exc}"
        if self.switch_command is None:
            return "MANUAL: 서비스·로봇 준비 완료, 켜기 명령을 직접 실행 (--switch-command 미지정)"
        if not self.execute:
            return "DRY-RUN OK: 실제 실행은 --execute"
        return "OK: 실제 동작 READY"

    def _service(self) -> None:
        shown = self.runner(["systemctl", "show", UNIT, "-p", "ActiveState,Result,NRestarts"])
        state = parse_properties(shown.stdout).get("ActiveState", "unknown")
        if state == "failed":
            self._mutate(["sudo", "systemctl", "reset-failed", UNIT])
            self._mutate(["sudo", "systemctl", "start", UNIT])
            self.report.add("서비스", "failed → reset-failed → start")
        elif state in {"inactive", "unknown"}:
            self._mutate(["sudo", "systemctl", "start", UNIT])
            self.report.add("서비스", f"{state} → start")
        elif state in {"active", "activating", "reloading"}:
            self.report.add("서비스", f"{state} (변경 없음)")
        else:
            raise StepFailed(f"서비스 상태 {state}: 수동 확인 필요")

    def _drop_in(self) -> None:
        source = DROP_IN_SOURCE / DROP_IN_NAME
        target = DROP_IN_DIR / DROP_IN_NAME
        same = self.runner(["cmp", "-s", str(source), str(target)])
        if same.returncode == 0:
            self.report.add("Restart=no", "설치됨")
            return
        self._mutate(["sudo", "install", "-D", "-m", "644", str(source), str(target)])
        self._mutate(["sudo", "systemctl", "daemon-reload"])
        self.report.add("Restart=no", "drop-in 설치 → daemon-reload (재부팅 후 유지)")

    def _queue(self) -> None:
        if not self.queue_cleared:
            raise StepFailed(
                "대기 실행 정리 미확인: Server 에서 오래된 대기 실행 정리 후 "
                "--queue-cleared 로 재실행"
            )
        self.report.add("대기 실행", "운영자 정리 확인")

    def _switch_on(self) -> None:
        if self.switch_command is None:
            self.report.add("켜기", "건너뜀(수동)")
            return
        result = self._mutate(self.switch_command)
        if result.returncode != 0:
            raise StepFailed(f"켜기 명령 실패(exit {result.returncode})")
        if not self.execute:
            self.report.add("켜기", "dry-run")
            return
        self._wait_for(
            "READY",
            lambda s: _physical(s).get("state") == "READY",
            "켜기 후 READY 아님: status.json 의 physicalExecution.reasons 확인",
        )
        self.report.add("켜기", "READY")

    def _mutate(self, command: Sequence[str]) -> CommandResult:
        return self.runner(command)

    def _wait_for(
        self,
        name: str,
        ready: Callable[[dict[str, object]], bool],
        failure: str,
    ) -> dict[str, object]:
        deadline = self.monotonic() + self.wait_seconds
        attempts = 0
        while True:
            attempts += 1
            status = self.status_reader(self.status_path)
            if status is not None and ready(status):
                self.report.add(name, f"확인({attempts}회)")
                return status
            if self.monotonic() >= deadline:
                raise StepFailed(failure)
            self.sleep(self.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true", help="actually run commands")
    parser.add_argument("--status-path", type=Path, default=STATUS_PATH)
    parser.add_argument("--queue-cleared", action="store_true")
    parser.add_argument("--switch-command", help="operator switch-on command, e.g. '<path> on'")
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument(
        "--simulate-state",
        default="failed",
        choices=["failed", "inactive", "active"],
        help="dry-run only: assumed service ActiveState",
    )
    parser.add_argument("--simulate-drop-in", action="store_true", help="dry-run only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner: Runner = (
        subprocess_runner
        if args.execute
        else DryRunRunner(args.simulate_state, args.simulate_drop_in)
    )
    starter = EventStart(
        runner=runner,
        status_path=args.status_path,
        execute=args.execute,
        queue_cleared=args.queue_cleared,
        switch_command=shlex.split(args.switch_command) if args.switch_command else None,
        wait_seconds=args.wait_seconds,
        poll_seconds=args.poll_seconds,
    )
    summary = starter.run()
    print(summary, flush=True)
    return 1 if summary.startswith("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
