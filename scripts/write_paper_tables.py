#!/usr/bin/env python3
"""Write plan2 Phase-13 tables/figures JSON from FORMAL_AGGREGATE.json."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def fmt_rate(r):
    if r is None:
        return "—"
    return f"{100.0 * r:.1f}%"


def fmt_ms(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:.1f}"


def fmt_num(v, nd=3):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:.{nd}f}"


def method_label(m):
    return {
        "original": "Original SANDO",
        "supervised": "Supervised One-shot",
        "true_diff": "DiffOpt One-shot",
    }.get(m, m)


ORDER = ["original", "supervised", "true_diff"]


def oneshot_rate(rows):
    # Episode-level: fraction of appends that were oneshot, averaged over episodes
    rates = []
    for r in rows:
        o = r.get("oneshot")
        # need fallback from raw? use episodes_with_oneshot as proxy if only oneshot count
        if isinstance(o, (int, float)):
            rates.append(1.0 if o > 0 else 0.0)
    return None if not rates else sum(rates) / len(rates)


def med(vals):
    vals = [v for v in vals if isinstance(v, (int, float)) and math.isfinite(v)]
    return None if not vals else statistics.median(vals)


def write_tables(agg: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    # MAIN: one row per method averaged across groups (simple mean of group rates)
    by_method = {m: [] for m in ORDER}
    fig_success = {"groups": {}}
    fig_latency = {"groups": {}}
    for gname, g in (agg.get("groups") or {}).items():
        fig_success["groups"][gname] = {}
        fig_latency["groups"][gname] = {}
        rows_by_m = {}
        for r in g.get("rows") or []:
            rows_by_m.setdefault(r["method"], []).append(r)
        for m in ORDER:
            rows = rows_by_m.get(m, [])
            if not rows:
                continue
            goal = sum(1 for r in rows if r.get("goal_reached")) / len(rows)
            cfg = sum(1 for r in rows if r.get("collision_free_goal_reached")) / len(rows)
            oneshot = oneshot_rate(rows)
            p50 = med([r.get("latency_p50_ms") for r in rows])
            p95 = med([r.get("latency_p95_ms") for r in rows])
            clear = med([r.get("minimum_clearance") for r in rows])
            by_method[m].append(
                {
                    "goal": goal,
                    "cfg": cfg,
                    "oneshot": oneshot,
                    "p50": p50,
                    "p95": p95,
                    "clear": clear,
                    "n": len(rows),
                }
            )
            fig_success["groups"][gname][m] = {"goal_rate": goal, "collision_free_goal_rate": cfg, "n": len(rows)}
            fig_latency["groups"][gname][m] = {"p50_median_ms": p50, "p95_median_ms": p95, "n": len(rows)}

    def mean_field(items, key):
        vals = [x[key] for x in items if x.get(key) is not None]
        return None if not vals else sum(vals) / len(vals)

    lines = [
        "# TABLE_MAIN",
        "",
        "| Method | Task Success | Collision-Free Success | One-shot Rate (episodes with ≥1) | P50 Latency (ms) | P95 Latency (ms) | Min Clearance |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in ORDER:
        items = by_method[m]
        if not items:
            continue
        lines.append(
            f"| {method_label(m)} | {fmt_rate(mean_field(items,'goal'))} | {fmt_rate(mean_field(items,'cfg'))} | "
            f"{fmt_rate(mean_field(items,'oneshot'))} | {fmt_ms(mean_field(items,'p50'))} | "
            f"{fmt_ms(mean_field(items,'p95'))} | {fmt_num(mean_field(items,'clear'))} |"
        )
    (out_dir / "TABLE_MAIN.md").write_text("\n".join(lines) + "\n")

    # Per-group latency / safety tables
    lat_lines = ["# TABLE_LATENCY", ""]
    saf_lines = ["# TABLE_SAFETY", ""]
    for gname, g in (agg.get("groups") or {}).items():
        lat_lines += [f"## {gname}", "", "| Method | n | P50 med (ms) | P95 med (ms) |", "|---|---:|---:|---:|"]
        saf_lines += [
            f"## {gname}",
            "",
            "| Method | n | Goal | Collision-free goal | Collision rate | Min clearance med |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        rows_by_m = {}
        for r in g.get("rows") or []:
            rows_by_m.setdefault(r["method"], []).append(r)
        for m in ORDER:
            rows = rows_by_m.get(m, [])
            if not rows:
                continue
            n = len(rows)
            p50 = med([r.get("latency_p50_ms") for r in rows])
            p95 = med([r.get("latency_p95_ms") for r in rows])
            goal = sum(1 for r in rows if r.get("goal_reached")) / n
            cfg = sum(1 for r in rows if r.get("collision_free_goal_reached")) / n
            col = [r.get("collision") for r in rows if r.get("collision") is not None]
            col_rate = None if not col else sum(1 for c in col if c) / len(col)
            clear = med([r.get("minimum_clearance") for r in rows])
            lat_lines.append(f"| {method_label(m)} | {n} | {fmt_ms(p50)} | {fmt_ms(p95)} |")
            saf_lines.append(
                f"| {method_label(m)} | {n} | {fmt_rate(goal)} | {fmt_rate(cfg)} | {fmt_rate(col_rate)} | {fmt_num(clear)} |"
            )
        lat_lines.append("")
        saf_lines.append("")
    (out_dir / "TABLE_LATENCY.md").write_text("\n".join(lat_lines) + "\n")
    (out_dir / "TABLE_SAFETY.md").write_text("\n".join(saf_lines) + "\n")
    (out_dir / "TABLE_ABLATION.md").write_text(
        "# TABLE_ABLATION\n\nPrimary ablation is Supervised vs DiffOpt (same Z, same online 1T+1Z+1QP).\n"
        "See paired bootstrap JSON for Δ with 95% CI.\n"
    )
    (out_dir / "FIG_SUCCESS_DATA.json").write_text(json.dumps(fig_success, indent=2) + "\n")
    (out_dir / "FIG_LATENCY_DATA.json").write_text(json.dumps(fig_latency, indent=2) + "\n")
    (out_dir / "FIG_TRAJECTORY_DATA.json").write_text(
        json.dumps({"note": "per-episode min clearance / latency in FORMAL_AGGREGATE rows"}, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    agg = json.loads(args.aggregate.read_text())
    write_tables(agg, args.out_dir)
    print(f"wrote tables under {args.out_dir}")


if __name__ == "__main__":
    main()
