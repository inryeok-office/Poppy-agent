"""Join Agent motion logs with field measurements into a CSV dataset (#102).

Input 1: Agent structured JSON logs (``journalctl -u poppy-agent -o cat`` or
lines with a prefix; the JSON object starts at the first ``{``).  Each
``execution_physical_turn_finished`` event (MOVE and TURN) becomes one row,
numbered per Execution in log order (``motion_index`` from 1).  The Execution
is the most recent ``execution_started`` before it.

Input 2 (optional): the field measurement CSV from
docs/r11-closed-loop-field-validation.md with columns ``execution_id``
(full id or its first 8 characters), ``motion_index``, ``measured``,
``lateral_cm``, ``surface`` and ``note``.  ``measured`` uses the command unit
(meters for MOVE, degrees for TURN).

Output: CSV on stdout or ``--output``.  Rows without a measurement keep empty
measurement fields and ``missing_measurement=1``; nothing is dropped silently.
Only allow-listed, secret-free log fields are read.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TextIO

MOTION_EVENT = "execution_physical_turn_finished"
STARTED_EVENT = "execution_started"
COLUMNS = (
    "timestamp",
    "execution_id",
    "motion_index",
    "command_type",
    "direction",
    "commanded",
    "unit",
    "command_rate",
    "planned_seconds",
    "elapsed_seconds",
    "stop_move_successes",
    "motion_status",
    "achieved",
    "measured",
    "error",
    "lateral_cm",
    "surface",
    "note",
    "missing_measurement",
)


def parse_log_lines(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            record = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("event"), str):
            yield record


def motion_rows(records: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    execution_id = ""
    index = 0
    for record in records:
        context = record.get("context")
        context = context if isinstance(context, dict) else {}
        if record["event"] == STARTED_EVENT:
            execution_id = str(context.get("execution_id", ""))
            index = 0
            continue
        if record["event"] != MOTION_EVENT:
            continue
        index += 1
        turn = context.get("command_type") == "TURN"
        rows.append(
            {
                "timestamp": record.get("timestamp", ""),
                "execution_id": execution_id,
                "motion_index": index,
                "command_type": context.get("command_type", ""),
                "direction": context.get("direction", ""),
                "commanded": context.get("angle_degrees" if turn else "distance_meters", ""),
                "unit": "deg" if turn else "m",
                "command_rate": context.get("vyaw" if turn else "vx", ""),
                "planned_seconds": context.get("duration_seconds", ""),
                "elapsed_seconds": context.get("elapsed_seconds", ""),
                "stop_move_successes": context.get("stop_move_successes", ""),
                "motion_status": context.get("execution_status", ""),
                "achieved": context.get("achieved_magnitude", ""),
            }
        )
    return rows


def load_measurements(stream: TextIO) -> dict[tuple[str, int], dict[str, str]]:
    measurements: dict[tuple[str, int], dict[str, str]] = {}
    for row in csv.DictReader(stream):
        key = (row.get("execution_id", "").strip()[:8], int(row.get("motion_index", "0")))
        measurements[key] = row
    return measurements


def join(
    rows: Sequence[dict[str, object]], measurements: dict[tuple[str, int], dict[str, str]]
) -> list[dict[str, object]]:
    joined = []
    for row in rows:
        key = (str(row["execution_id"])[:8], int(str(row["motion_index"])))
        measured = measurements.get(key)
        out = dict(row)
        value = (measured or {}).get("measured", "").strip()
        if value:
            out["measured"] = value
            try:
                out["error"] = round(float(value) - float(str(row["commanded"])), 4)
            except ValueError:
                out["error"] = ""
            out["missing_measurement"] = 0
        else:
            out["measured"] = out["error"] = ""
            out["missing_measurement"] = 1
        for name in ("lateral_cm", "surface", "note"):
            out[name] = (measured or {}).get(name, "")
        joined.append(out)
    return joined


def write_csv(rows: Sequence[dict[str, object]], stream: TextIO) -> None:
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in COLUMNS})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", type=Path, help="Agent JSON log file")
    parser.add_argument("--measurements", type=Path, help="field measurement CSV")
    parser.add_argument("--output", type=Path, help="output CSV (default stdout)")
    args = parser.parse_args(argv)
    with args.log.open(encoding="utf-8") as log:
        rows = motion_rows(parse_log_lines(log))
    measurements: dict[tuple[str, int], dict[str, str]] = {}
    if args.measurements is not None:
        with args.measurements.open(encoding="utf-8", newline="") as stream:
            measurements = load_measurements(stream)
    joined = join(rows, measurements)
    if args.output is None:
        write_csv(joined, sys.stdout)
    else:
        with args.output.open("w", encoding="utf-8", newline="") as stream:
            write_csv(joined, stream)
    missing = sum(1 for row in joined if row["missing_measurement"] == 1)
    print(f"rows={len(joined)} missing_measurement={missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
