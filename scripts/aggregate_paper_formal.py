#!/usr/bin/env python3
"""Aggregate paper formal A/B/C closed-loop results into one summary JSON."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def _load_result(run_dir: Path):
    path = run_dir / "result.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _collision(result):
    gt = (result or {}).get("ground_truth") or {}
    col = gt.get("collision") if isinstance(gt.get("collision"), dict) else {}
    return col


def summarize_group(group_dir: Path):
    rows = []
    for method_dir in sorted(p for p in group_dir.iterdir() if p.is_dir()):
        method = method_dir.name
        if method.startswith("."):
            continue
        for seed_dir in sorted(method_dir.glob("seed*")):
            result = _load_result(seed_dir / "run")
            summary_path = seed_dir / "summary.json"
            pilot = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
            col = _collision(result)
            goal = bool((result or {}).get("goal_reached") or pilot.get("goal_reached"))
            collision = col.get("collision")
            rows.append(
                {
                    "method": method,
                    "seed": int(seed_dir.name.replace("seed", "")),
                    "goal_reached": goal,
                    "collision": collision,
                    "collision_free": (collision is False) if collision is not None else None,
                    "collision_free_goal_reached": goal and collision is False,
                    "minimum_clearance": col.get("minimum_clearance"),
                    "aabb_proxy_collision": col.get("aabb_proxy_collision"),
                    "oneshot": pilot.get("oneshot_append_no_fallback"),
                    "latency_p50_ms": pilot.get("latency_p50_ms"),
                    "latency_p95_ms": pilot.get("latency_p95_ms"),
                    "controller_first_use_events": pilot.get("controller_first_use_events"),
                }
            )
    by_method = {}
    for row in rows:
        by_method.setdefault(row["method"], []).append(row)

    def rate(vals):
        vals = [v for v in vals if v is not None]
        return None if not vals else sum(1 for v in vals if v) / len(vals)

    def wilson(successes: int, n: int, z: float = 1.96):
        if n <= 0:
            return None
        p = successes / n
        den = 1 + z * z / n
        center = (p + z * z / (2 * n)) / den
        half = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
        return {"estimate": p, "ci95": [max(0.0, center - half), min(1.0, center + half)], "n": n, "k": successes}

    def med(vals):
        vals = [v for v in vals if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
        return None if not vals else statistics.median(vals)

    methods = {}
    for method, items in by_method.items():
        goal = [bool(r["goal_reached"]) for r in items]
        cfg = [bool(r["collision_free_goal_reached"]) for r in items]
        col = [r["collision"] for r in items if r["collision"] is not None]
        oneshot_eps = []
        for r in items:
            o = r.get("oneshot")
            fb = None
            # episode-level oneshot success: any oneshot append and no fallback preferred;
            # report fraction of appends that were oneshot when counts present
            if isinstance(o, (int, float)):
                oneshot_eps.append(o > 0)
        methods[method] = {
            "n": len(items),
            "goal_rate": rate(goal),
            "goal_wilson95": wilson(sum(goal), len(goal)),
            "collision_free_goal_rate": rate(cfg),
            "collision_free_goal_wilson95": wilson(sum(1 for v in cfg if v), len(cfg)),
            "collision_rate": rate(col),
            "episodes_with_oneshot_append": rate(oneshot_eps) if oneshot_eps else None,
            "oneshot_append_wilson95": wilson(sum(1 for v in oneshot_eps if v), len(oneshot_eps)) if oneshot_eps else None,
            "latency_p50_median_ms": med([r["latency_p50_ms"] for r in items]),
            "latency_p95_median_ms": med([r["latency_p95_ms"] for r in items]),
            "min_clearance_median": med([r["minimum_clearance"] for r in items]),
            "median_oneshot_appends": med([r["oneshot"] for r in items if isinstance(r.get("oneshot"), (int, float))]),
        }
    return {"group_dir": str(group_dir), "n_rows": len(rows), "methods": methods, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group_dirs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    groups = {p.name: summarize_group(p) for p in args.group_dirs if p.is_dir()}
    payload = {"schema_version": 1, "kind": "paper_formal_aggregate", "groups": groups}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({g: {m: d["methods"].get(m) for m in d["methods"]} for g, d in groups.items()}, indent=2))


if __name__ == "__main__":
    main()
