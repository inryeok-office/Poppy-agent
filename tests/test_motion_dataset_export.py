"""scripts/motion_dataset_export.py with synthetic log lines only (#102)."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "motion_dataset_export", ROOT / "scripts" / "motion_dataset_export.py"
)
assert SPEC is not None and SPEC.loader is not None
export = importlib.util.module_from_spec(SPEC)
sys.modules["motion_dataset_export"] = export
SPEC.loader.exec_module(export)

EXEC_A = "0e1f2a3b-0000-0000-0000-000000000001"
EXEC_B = "9f8e7d6c-0000-0000-0000-000000000002"


def line(event: str, prefix: str = "", **context: object) -> str:
    payload = {"timestamp": "2026-11-12T00:00:00+00:00", "event": event, "context": context}
    return prefix + json.dumps(payload) + "\n"


LOG = [
    "-- Boot abc --\n",
    line("execution_started", execution_id=EXEC_A),
    line(
        "execution_physical_turn_finished",
        prefix="Nov 12 09:00:01 host python[1]: ",
        execution_status="COMPLETED",
        command_type="MOVE",
        direction="FORWARD",
        distance_meters=1.0,
        vx=0.5,
        duration_seconds=2.0,
        elapsed_seconds=2.01,
        stop_move_successes=3,
    ),
    line(
        "execution_physical_turn_finished",
        execution_status="COMPLETED",
        command_type="TURN",
        direction="LEFT",
        angle_degrees=90,
        vyaw=0.785,
        duration_seconds=2.0,
        achieved_magnitude=88.5,
    ),
    "not json {broken\n",
    line("execution_started", execution_id=EXEC_B),
    line(
        "execution_physical_turn_finished",
        execution_status="FAILED",
        command_type="MOVE",
        direction="BACKWARD",
        distance_meters=0.5,
    ),
    line("heartbeat_sent"),
]

MEASUREMENTS = """execution_id,motion_index,measured,lateral_cm,surface,note
0e1f2a3b,1,1.04,2,mat,
0e1f2a3b-0000-0000-0000-000000000001,2,91.0,,mat,clockwise check
"""


def run_export() -> list[dict[str, str]]:
    rows = export.motion_rows(export.parse_log_lines(LOG))
    joined = export.join(rows, export.load_measurements(io.StringIO(MEASUREMENTS)))
    out = io.StringIO()
    export.write_csv(joined, out)
    out.seek(0)
    return list(csv.DictReader(out))


def test_rows_are_numbered_per_execution_with_units() -> None:
    rows = run_export()
    assert [(r["execution_id"][:8], r["motion_index"]) for r in rows] == [
        ("0e1f2a3b", "1"),
        ("0e1f2a3b", "2"),
        ("9f8e7d6c", "1"),
    ]
    assert [(r["command_type"], r["commanded"], r["unit"]) for r in rows] == [
        ("MOVE", "1.0", "m"),
        ("TURN", "90", "deg"),
        ("MOVE", "0.5", "m"),
    ]
    assert rows[0]["command_rate"] == "0.5" and rows[1]["command_rate"] == "0.785"
    assert rows[1]["achieved"] == "88.5"


def test_measurements_join_by_short_or_full_id_and_compute_error() -> None:
    rows = run_export()
    assert (rows[0]["measured"], rows[0]["error"], rows[0]["lateral_cm"]) == ("1.04", "0.04", "2")
    assert (rows[1]["measured"], rows[1]["error"]) == ("91.0", "1.0")
    assert rows[1]["surface"] == "mat"


def test_missing_measurement_is_kept_and_flagged() -> None:
    rows = run_export()
    assert rows[2]["missing_measurement"] == "1"
    assert rows[2]["measured"] == "" and rows[2]["motion_status"] == "FAILED"
    assert [r["missing_measurement"] for r in rows[:2]] == ["0", "0"]


def test_cli_writes_csv_and_reports_counts(tmp_path: Path, capsys) -> None:
    log = tmp_path / "agent.log"
    log.write_text("".join(LOG), encoding="utf-8")
    measured = tmp_path / "measured.csv"
    measured.write_text(MEASUREMENTS, encoding="utf-8")
    output = tmp_path / "dataset.csv"

    assert export.main([str(log), "--measurements", str(measured), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8").splitlines()[0].startswith("timestamp,execution_id")
    assert "rows=3 missing_measurement=1" in capsys.readouterr().err


def test_columns_hold_no_identity_or_secret_fields() -> None:
    forbidden = {"agent_id", "robot_id", "approval_ref", "token", "ip"}
    assert forbidden.isdisjoint(export.COLUMNS)
