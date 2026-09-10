#!/usr/bin/env python3
"""Attribute formal episode failures into plan2 buckets (primary label)."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def primary_bucket(result: dict, pilot: dict) -> str:
    goal = bool(result.get("goal_reached") or pilot.get("goal_reached"))
    col = ((result.get("ground_truth") or {}).get("collision") or {})
    collision = col.get("collision")
    if goal and collision is False:
        return "success_collision_free"
    if goal and collision is True:
        return "execution_tracking"
    if result.get("error"):
        err = str(result.get("error"))
        if "odom" in err.lower() or "ready" in err.lower():
            return "map_sensing"
        return "other"
    stages = pilot.get("failure_stage") or {}
    # dominant failure stage among planning attempts
    if isinstance(stages, dict) and stages:
        # ignore None/"None" success-ish counters when picking primary failure
        ranked = sorted(
            ((k, v) for k, v in stages.items() if str(k) not in ("None", "null")),
            key=lambda kv: kv[1],
            reverse=True,
        )
        if ranked:
            top = str(ranked[0][0])
            if "corridor" in top:
                return "wrong_Z"
            if "optim" in top:
                return "optimizer"
            if "global" in top or "map" in top:
                return "map_sensing"
            return "other"
    if pilot.get("fallback_append", 0) and not pilot.get("oneshot_append_no_fallback", 0):
        return "timing_T"  # conservative: heavy fallback without oneshot
    if not goal:
        return "unknown"
    return "other"


def scan_group(group_dir: Path):
    rows = []
    for method_dir in sorted(p for p in group_dir.iterdir() if p.is_dir()):
        for seed_dir in sorted(method_dir.glob("seed*")):
            result_path = seed_dir / "run" / "result.json"
            summary_path = seed_dir / "summary.json"
            if not result_path.is_file():
                continue
            result = json.loads(result_path.read_text())
            pilot = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
            bucket = primary_bucket(result, pilot)
            rows.append(
                {
                    "method": method_dir.name,
                    "seed": int(seed_dir.name.replace("seed", "")),
                    "bucket": bucket,
                    "goal_reached": bool(result.get("goal_reached") or pilot.get("goal_reached")),
                    "collision": ((result.get("ground_truth") or {}).get("collision") or {}).get("collision"),
                }
            )
    counts = Counter((r["method"], r["bucket"]) for r in rows)
    return {
        "group": group_dir.name,
        "n": len(rows),
        "counts": {f"{m}|{b}": c for (m, b), c in sorted(counts.items())},
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group_dirs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    groups = [scan_group(p) for p in args.group_dirs if p.is_dir()]
    # wrong-Z dominance gate
    wrong = sum(g["counts"].get(f"{m}|wrong_Z", 0) for g in groups for m in ("supervised", "true_diff"))
    total_fail = sum(
        c
        for g in groups
        for k, c in g["counts"].items()
        if not k.endswith("|success_collision_free")
    )
    payload = {
        "schema_version": 1,
        "kind": "paper_failure_attribution",
        "groups": groups,
        "wrong_Z_count_learned": wrong,
        "non_success_count": total_fail,
        "restart_Z_learning": bool(total_fail and wrong / max(total_fail, 1) >= 0.5),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in payload if k != "groups"}, indent=2))


if __name__ == "__main__":
    main()
