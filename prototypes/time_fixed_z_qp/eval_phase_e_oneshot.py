#!/usr/bin/env python3
"""Offline one-shot eval for Phase E timing models on train16 pack."""

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
from run_time_qp import build_spec, segment_dt, solve_hard_qp  # noqa: E402
from train_time_nn_qp import F_MAX, F_MIN, instance_from_pack_item  # noqa: E402
from integer_timing_policy import SINGLE_LOG_BOUNDS  # noqa: E402

LOG_LO, LOG_HI = SINGLE_LOG_BOUNDS


def predict_f(model_path: Path, item: dict) -> float:
    model = load_model(json.loads(model_path.read_text()))
    net = model["model"]
    mean = np.asarray(model["mean"], dtype=np.float64)
    std = np.asarray(model["std"], dtype=np.float64)
    x = torch.tensor(normalize(raw_features(item["instance"]), mean, std), dtype=torch.float64)
    with torch.no_grad():
        log_f = torch.clamp(net(x), LOG_LO, LOG_HI)
        f = float(torch.exp(log_f).clamp(F_MIN, F_MAX))
    return f


def eval_model(pack: dict, model_path: Path | None, label: str, use_capture_factor: bool = False):
    rows = []
    accept = 0
    for item in pack["items"]:
        qp = instance_from_pack_item(item)
        if use_capture_factor:
            f = float(item["factor_capture"])
        else:
            f = predict_f(model_path, item)
        hard = solve_hard_qp(build_spec(qp, f), item["assignment"])
        ok = "jerk" in hard
        if ok:
            accept += 1
        rows.append(
            {
                "id": f"{item['scene_id']}:{item['request_id']}",
                "f": f,
                "accept": ok,
                "jerk": hard.get("jerk"),
                "T": 5.0 * segment_dt(qp["initial_dt"], qp["dc"], f),
                "status": hard.get("status"),
            }
        )
    n = len(pack["items"])
    return {
        "label": label,
        "model": str(model_path) if model_path else "capture_factor",
        "n": n,
        "main_qp_accept": accept,
        "main_qp_accept_rate": accept / n if n else 0.0,
        "failures_in_denominator": True,
        "mean_jerk_accepted": float(
            np.mean([r["jerk"] for r in rows if r["jerk"] is not None])
        )
        if accept
        else None,
        "mean_T": float(np.mean([r["T"] for r in rows])),
        "rows": rows,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pack", type=Path, default=Path("evidence/train16_pack_geometry.json"))
    p.add_argument("--out", type=Path, default=Path("evidence/phase_e_train/offline_oneshot_compare.json"))
    p.add_argument("--models", nargs="*", type=Path, default=[])
    args = p.parse_args()
    pack = json.loads(args.pack.read_text())
    results = [eval_model(pack, None, "capture_factor_oracle", use_capture_factor=True)]
    # supervised init
    supervised = ROOT / "docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json"
    if supervised.is_file():
        results.append(eval_model(pack, supervised, "supervised_init"))
    for m in args.models:
        results.append(eval_model(pack, m, m.stem))
    # auto-discover phase_e models if none given
    if not args.models:
        for m in sorted((Path("evidence/phase_e_train")).glob("timing_*.json")):
            results.append(eval_model(pack, m, m.stem))
    out = {
        "schema_version": 1,
        "kind": "phase_e_offline_oneshot_compare",
        "pack": str(args.pack),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({r["label"]: {"accept": r["main_qp_accept"], "rate": r["main_qp_accept_rate"], "mean_jerk": r["mean_jerk_accepted"]} for r in results}, indent=2))


if __name__ == "__main__":
    main()
