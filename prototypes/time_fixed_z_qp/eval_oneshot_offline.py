#!/usr/bin/env python3
"""Offline one-shot chain: timing MLP → one f → fixed Z → one hard QP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from integer_timing_policy import load_model, normalize, raw_features  # noqa: E402
from run_time_qp import build_spec, solve_hard_qp  # noqa: E402
from train_time_nn_qp import F_MAX, F_MIN, clamp_log, instance_from_pack_item  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--timing-model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pack = json.loads(args.pack.read_text())
    model = load_model(json.loads(args.timing_model.read_text()))
    net = model["model"]
    mean = np.asarray(model["mean"], dtype=np.float64)
    std = np.asarray(model["std"], dtype=np.float64)

    rows = []
    for item in pack["items"]:
        qp = instance_from_pack_item(item)
        x = torch.tensor(normalize(raw_features(item["instance"]), mean, std), dtype=torch.float64)
        with torch.no_grad():
            factor = float(torch.exp(clamp_log(net(x).reshape(()))))
        factor = min(F_MAX, max(F_MIN, factor))
        solved = solve_hard_qp(build_spec(qp, factor), item["assignment"])
        rows.append(
            {
                "id": f"{item['scene_id']}:{item['request_id']}",
                "assignment": item["assignment"],
                "f": factor,
                "status": solved.get("status"),
                "jerk": solved.get("jerk"),
                "main_qp_ok": "jerk" in solved,
                "fallback_used": False,
                "main_t_count": 1,
                "main_z_count": 1,
                "main_qp_count": 1,
            }
        )

    n = len(rows)
    n_ok = sum(1 for r in rows if r["main_qp_ok"])
    report = {
        "n": n,
        "main_qp_accept": n_ok,
        "main_qp_accept_rate": n_ok / n if n else 0.0,
        "fallback_calls": 0,
        "one_shot_definition": "exactly one T, one Z, one hard QP; fallback counted separately",
        "timing_model": str(args.timing_model),
        "pack": str(args.pack),
        "rows": rows,
        "status": "passed" if n_ok == n else "partial",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
    if report["status"] == "partial" and n_ok == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
