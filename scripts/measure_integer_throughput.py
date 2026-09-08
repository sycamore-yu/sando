#!/usr/bin/env python3
"""Read-only throughput measurements from completed capture snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def measure_root(root: Path) -> dict[str, Any]:
    scenes = []
    for output in sorted(root.glob("*/seed*/output.json")):
        data = json.loads(output.read_text())
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
            })
    elapsed = [item["elapsed_sec"] for item in scenes if isinstance(item["elapsed_sec"], (int, float))]
    retained = [item["retained"] or 0 for item in scenes]
    hours = sum(elapsed) / 3600.0 if elapsed else 0.0
    return {
        "scenes": len(scenes),
        "retained_instances": sum(retained),
        "flight_hours": hours,
        "instances_per_flight_hour": (sum(retained) / hours) if hours else None,
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
