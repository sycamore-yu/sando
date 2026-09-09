#!/usr/bin/env python3
"""Read-only throughput measurements from completed capture snapshots."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def measure_root(root: Path) -> dict[str, Any]:
    scenes = []
    campaigns = []
    intervals = []
    for output in sorted(root.glob("*/seed*/output.json")):
        data = json.loads(output.read_text())
        if not data.get("completed") or data.get("required_capture_invalid"):
            continue
        campaigns.append(data)
        try:
            intervals.append((datetime.fromisoformat(data["created_utc"]).timestamp(),
                              datetime.fromisoformat(data["completed_utc"]).timestamp()))
        except (KeyError, TypeError, ValueError):
            pass
        seed_dir = output.parent
        for run_dir in sorted((seed_dir / "runs").glob("*")):
            result_path = run_dir / "result.json"
            summary_path = run_dir / "instances.jsonl.summary.json"
            if not result_path.is_file():
                continue
            result = json.loads(result_path.read_text())
            summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
            scenes.append({
                "run": run_dir.name,
                "elapsed_sec": result.get("elapsed_sec"),
                "success": result.get("success"),
                "retained": summary.get("retained"),
                "eligible": summary.get("total_eligible") or summary.get("eligible"),
                "goal_distance_m": result.get("goal_distance_m"),
                "error": result.get("error"),
                "qualified": bool(data.get("completed") and result.get("success") and summary.get("retained")
                                  and not result.get("instrumentation_error")
                                  and (not isinstance(result.get("simulation_health"), dict)
                                       or result["simulation_health"].get("valid") is not False)),
                "valid_retained": bool(summary.get("retained") and not result.get("instrumentation_error")
                                       and (not isinstance(result.get("simulation_health"), dict)
                                            or result["simulation_health"].get("valid") is not False)),
            })
    elapsed = [item["elapsed_sec"] for item in scenes if isinstance(item["elapsed_sec"], (int, float))]
    retained = [item["retained"] or 0 for item in scenes if item["qualified"]]
    flight_seconds = sum(item["elapsed_sec"] for item in scenes
                         if item["qualified"] and isinstance(item["elapsed_sec"], (int, float)))
    merged = []
    for start, end in sorted(intervals):
        if end > start:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
    union_seconds = sum(end - start for start, end in merged)
    wall_seconds = (max(end for start, end in intervals) - min(start for start, end in intervals)) if intervals else 0.0
    hours = flight_seconds / 3600.0
    wall_hours = wall_seconds / 3600.0
    total_retained = sum(retained)
    return {
        "scenes": len(scenes),
        "retained_instances": total_retained,
        "qualified_retained_instances": total_retained,
        "all_valid_retained_instances": sum(item["retained"] for item in scenes if item["valid_retained"]),
        "all_valid_instances_per_wall_hour": (sum(item["retained"] for item in scenes if item["valid_retained"]) / wall_hours) if wall_hours else None,
        "flight_hours": hours,
        "sum_flight_hours": hours,
        "wall_interval_sec": wall_seconds,
        "union_wall_interval_sec": union_seconds,
        "wall_hours": wall_hours,
        "instances_per_flight_hour": (total_retained / hours) if hours else None,
        "instances_per_wall_hour": (total_retained / wall_hours) if wall_hours else None,
        "success_true": sum(1 for item in scenes if item["success"]),
        "rows": scenes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = measure_root(Path(args.input))
    Path(args.output).write_text(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2) + "\n")
    Path(args.output).with_suffix(".full.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "rows"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
