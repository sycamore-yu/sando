#!/usr/bin/env python3
"""Paired bootstrap CIs for formal A/B/C (plan2 STATISTICS)."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def bootstrap_mean_diff(a, b, n_boot=5000, seed=0):
    """Paired a[i]-b[i] mean with percentile 95% CI. a,b same length floats/bools."""
    paired = [float(x) - float(y) for x, y in zip(a, b)]
    n = len(paired)
    if n == 0:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [paired[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot) - 1]
    return {"mean_diff": sum(paired) / n, "ci95": [lo, hi], "n": n}


def rows_by_seed(group: dict, method: str):
    out = {}
    for r in group.get("rows") or []:
        if r.get("method") == method:
            out[r["seed"]] = r
    return out


def compare(group: dict, ma: str, mb: str):
    a = rows_by_seed(group, ma)
    b = rows_by_seed(group, mb)
    seeds = sorted(set(a) & set(b))
    if not seeds:
        return None
    cfg_a = [1.0 if a[s].get("collision_free_goal_reached") else 0.0 for s in seeds]
    cfg_b = [1.0 if b[s].get("collision_free_goal_reached") else 0.0 for s in seeds]
    lat_a = [a[s]["latency_p50_ms"] for s in seeds if a[s].get("latency_p50_ms") is not None and b[s].get("latency_p50_ms") is not None]
    lat_b = [b[s]["latency_p50_ms"] for s in seeds if a[s].get("latency_p50_ms") is not None and b[s].get("latency_p50_ms") is not None]
    return {
        "seeds": seeds,
        "collision_free_goal_A_minus_B": bootstrap_mean_diff(cfg_a, cfg_b),
        "latency_p50_A_minus_B_ms": bootstrap_mean_diff(lat_a, lat_b) if lat_a else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    agg = json.loads(args.aggregate.read_text())
    pairs = [
        ("supervised", "original"),
        ("true_diff", "original"),
        ("true_diff", "supervised"),
    ]
    out = {"schema_version": 1, "kind": "paper_paired_bootstrap", "groups": {}}
    for gname, g in (agg.get("groups") or {}).items():
        out["groups"][gname] = {
            f"{a}_minus_{b}": compare(g, a, b) for a, b in pairs
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: list(v.keys()) for k, v in out["groups"].items()}, indent=2))


if __name__ == "__main__":
    main()
