#!/usr/bin/env python3
"""Fill RQ_ANSWERS.md + executive summary numbers from formal artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def wilson_str(w):
    if not w:
        return "—"
    lo, hi = w["ci95"]
    return f"{100*w['estimate']:.1f}% [{100*lo:.1f}, {100*hi:.1f}] (n={w['n']})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("docs/paper-study-v2"))
    args = parser.parse_args()
    root = args.root
    agg = json.loads((root / "FORMAL_AGGREGATE.json").read_text())
    attr = json.loads((root / "FAILURE_ATTRIBUTION.json").read_text()) if (root / "FAILURE_ATTRIBUTION.json").is_file() else {}
    boot = json.loads((root / "PAIRED_BOOTSTRAP.json").read_text()) if (root / "PAIRED_BOOTSTRAP.json").is_file() else {}

    lines = ["# RQ1–RQ3 answers (filled from formal evidence)", ""]
    lines.append("## Per-group method summary")
    lines.append("")
    for gname, g in (agg.get("groups") or {}).items():
        lines.append(f"### {gname}")
        lines.append("")
        for m, s in (g.get("methods") or {}).items():
            lines.append(
                f"- **{m}**: collision-free goal {wilson_str(s.get('collision_free_goal_wilson95'))}; "
                f"goal {wilson_str(s.get('goal_wilson95'))}; "
                f"P50 med {s.get('latency_p50_median_ms')}; "
                f"episodes with oneshot {s.get('episodes_with_oneshot_append')}"
            )
        lines.append("")

    lines += [
        "## RQ1 — Learned one-shot vs Original",
        "",
        "Compare Supervised/DiffOpt vs Original on latency and collision-free goal (paired).",
        "Original oneshot_append is structurally ~0; do not treat that as a fair oneshot-rate contest.",
        "",
        "## RQ2 — DiffOpt vs Supervised",
        "",
        "Paired bootstrap (`PAIRED_BOOTSTRAP.json` true_diff_minus_supervised).",
        "",
        "## RQ3 — Why",
        "",
        f"- wrong_Z_count_learned: {attr.get('wrong_Z_count_learned')}",
        f"- non_success_count: {attr.get('non_success_count')}",
        f"- restart_Z_learning: {attr.get('restart_Z_learning')}",
        "",
        "Z stays frozen unless restart_Z_learning is true.",
        "",
        "## Bootstrap pointer",
        "",
        "```json",
        json.dumps(boot.get("groups", {}), indent=2)[:4000],
        "```",
        "",
    ]
    (root / "RQ_ANSWERS.md").write_text("\n".join(lines) + "\n")
    print("wrote", root / "RQ_ANSWERS.md")


if __name__ == "__main__":
    main()
