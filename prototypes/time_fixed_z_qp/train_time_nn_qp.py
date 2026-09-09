#!/usr/bin/env python3
"""Train the schema-2 timing MLP with fixed-C/fixed-Z QP trajectory cost.

Loss = J_trajectory(B*(f), f) / J_scale   (lambda_T = 0)
f = exp(clamp(net(x))) in [1, 2.5]
QP gradient w.r.t. f via central FD; network gets that scalar through autograd.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from integer_timing_policy import (  # noqa: E402
    FEATURE_DIM,
    SINGLE_LOG_BOUNDS,
    build_mlp,
    load_model,
    normalize,
    raw_features,
)
from run_time_qp import build_spec, load_planning_instance, segment_dt, solve_hard_qp  # noqa: E402

F_MIN, F_MAX = 1.0, 2.5
J_SCALE = 1.0e5
LOG_LO, LOG_HI = SINGLE_LOG_BOUNDS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clamp_log(value: torch.Tensor) -> torch.Tensor:
    return torch.clamp(value, LOG_LO, LOG_HI)


def build_pack(selected60_jsonl: Path, replay_jsonl: Path, out_path: Path, n: int = 16):
    by = {}
    for line in selected60_jsonl.open():
        inst = json.loads(line)
        by[(inst["scene_id"], str(inst["request_id"]))] = inst

    picks = []
    for line in replay_jsonl.open():
        row = json.loads(line)
        method = row["methods"]["cost"]
        attempts = method.get("attempts") or []
        if not attempts:
            continue
        first = attempts[0]
        if not (first.get("accepted") and not first.get("fallback") and first.get("assignment")):
            continue
        key = (row["scene_id"], str(row["request_id"]))
        if key not in by:
            continue
        inst = by[key]
        assignment = [int(v) for v in first["assignment"]]
        # Smoke feasibility at captured factor with this Z.
        loaded = {
            "path": f"selected60:{key[0]}:{key[1]}",
            "N": int(inst["n"]),
            "P": len(inst["corridors"][0]),
            "initial_dt": float(inst["initial_dt"]),
            "dc": float(inst["dc"]),
            "native_factor": float(inst["factor"]),
            "x0": np.asarray(inst["start"], dtype=float),
            "xf": np.asarray(inst["goal"], dtype=float),
            "map_lower": np.asarray(
                [inst["map_bounds"][0], inst["map_bounds"][2], inst["map_bounds"][4]], dtype=float
            ),
            "map_upper": np.asarray(
                [inst["map_bounds"][1], inst["map_bounds"][3], inst["map_bounds"][5]], dtype=float
            ),
            "limits": {"velocity": 5.0, "acceleration": 20.0, "jerk": 100.0},
            "jerk_weight": 10.0,
            "corridors": [
                [{"A": np.asarray([[p[0], p[1], p[2]] for p in poly["planes"]], float),
                  "b": np.asarray([p[3] for p in poly["planes"]], float)} for poly in layer]
                for layer in inst["corridors"]
            ],
            "valid": np.asarray(inst["valid_mask"], dtype=bool),
            "raw_instance": inst,
            "assignment": assignment,
        }
        probe = solve_hard_qp(build_spec(loaded, float(inst["factor"])), assignment)
        if "jerk" not in probe:
            continue
        picks.append(
            {
                "scene_id": key[0],
                "request_id": key[1],
                "factor_capture": float(inst["factor"]),
                "assignment": assignment,
                "jerk_at_capture": probe["jerk"],
                "instance": {
                    k: inst[k]
                    for k in (
                        "n",
                        "norm",
                        "planner",
                        "scene_id",
                        "episode_id",
                        "request_id",
                        "factor_id",
                        "source_id",
                        "config_id",
                        "factor",
                        "initial_dt",
                        "dc",
                        "segment_dt",
                        "start",
                        "goal",
                        "map_bounds",
                        "corridors",
                        "valid_mask",
                    )
                    if k in inst
                },
            }
        )
        if len(picks) >= n:
            break

    if len(picks) < n:
        raise SystemExit(f"only found {len(picks)} feasible pack members, need {n}")
    payload = {
        "n": len(picks),
        "source_selected60": str(selected60_jsonl),
        "source_replay": str(replay_jsonl),
        "items": picks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload))
    print(json.dumps({"wrote": str(out_path), "n": len(picks)}, indent=2))


def instance_from_pack_item(item):
    inst = item["instance"]
    return {
        "path": f"pack:{item['scene_id']}:{item['request_id']}",
        "N": int(inst["n"]),
        "P": len(inst["corridors"][0]),
        "initial_dt": float(inst["initial_dt"]),
        "dc": float(inst["dc"]),
        "native_factor": float(inst["factor"]),
        "x0": np.asarray(inst["start"], dtype=float),
        "xf": np.asarray(inst["goal"], dtype=float),
        "map_lower": np.asarray(
            [inst["map_bounds"][0], inst["map_bounds"][2], inst["map_bounds"][4]], dtype=float
        ),
        "map_upper": np.asarray(
            [inst["map_bounds"][1], inst["map_bounds"][3], inst["map_bounds"][5]], dtype=float
        ),
        "limits": {"velocity": 5.0, "acceleration": 20.0, "jerk": 100.0},
        "jerk_weight": 10.0,
        "corridors": [
            [
                {
                    "A": np.asarray([[p[0], p[1], p[2]] for p in poly["planes"]], float),
                    "b": np.asarray([p[3] for p in poly["planes"]], float),
                }
                for poly in layer
            ]
            for layer in inst["corridors"]
        ],
        "valid": np.asarray(inst["valid_mask"], dtype=bool),
    }


def fd_dJ_df(qp_instance, assignment, factor, eps=1e-4):
    plus = solve_hard_qp(build_spec(qp_instance, min(F_MAX, factor + eps)), assignment)
    minus = solve_hard_qp(build_spec(qp_instance, max(F_MIN, factor - eps)), assignment)
    if "jerk" not in plus or "jerk" not in minus:
        return None
    return (plus["jerk"] - minus["jerk"]) / (2 * eps)


def train(pack_path: Path, init_model: Path, out_dir: Path, steps: int, lr: float, seed: int):
    pack = json.loads(pack_path.read_text())
    items = pack["items"]
    torch.manual_seed(seed)
    np.random.seed(seed)

    model = load_model(json.loads(Path(init_model).read_text()))
    net = model["model"]
    mean = np.asarray(model["mean"], dtype=np.float64)
    std = np.asarray(model["std"], dtype=np.float64)
    opt = torch.optim.Adam(net.parameters(), lr=lr)

    prepared = []
    for item in items:
        qp = instance_from_pack_item(item)
        feats = raw_features(item["instance"])
        prepared.append(
            {
                "qp": qp,
                "assignment": item["assignment"],
                "x": torch.tensor(normalize(feats, mean, std), dtype=torch.float64),
                "id": f"{item['scene_id']}:{item['request_id']}",
            }
        )

    history = []
    for step in range(steps):
        order = np.random.permutation(len(prepared))
        step_rows = []
        loss_vals = []
        for idx in order:
            sample = prepared[int(idx)]
            opt.zero_grad(set_to_none=True)
            log_f = clamp_log(net(sample["x"]).reshape(()))
            factor = float(torch.exp(log_f).detach())
            solved = solve_hard_qp(build_spec(sample["qp"], factor), sample["assignment"])
            if "jerk" not in solved:
                step_rows.append(
                    {
                        "id": sample["id"],
                        "f": factor,
                        "status": solved.get("status"),
                        "accepted_grad": False,
                    }
                )
                continue
            jerk = float(solved["jerk"])
            g = fd_dJ_df(sample["qp"], sample["assignment"], factor)
            if g is None:
                step_rows.append(
                    {
                        "id": sample["id"],
                        "f": factor,
                        "jerk": jerk,
                        "status": "fd_failed",
                        "accepted_grad": False,
                    }
                )
                continue
            # dJ/d log_f = dJ/df * f ; proxy loss for autograd
            dJ_dlogf = g * factor
            proxy = (torch.tensor(dJ_dlogf / J_SCALE, dtype=torch.float64) * log_f)
            proxy.backward()
            opt.step()
            loss_vals.append(jerk / J_SCALE)
            step_rows.append(
                {
                    "id": sample["id"],
                    "f": factor,
                    "T": 5 * segment_dt(sample["qp"]["initial_dt"], sample["qp"]["dc"], factor),
                    "jerk": jerk,
                    "dJ_df": g,
                    "accepted_grad": True,
                    "status": "optimal",
                }
            )
        mean_loss = float(np.mean(loss_vals)) if loss_vals else None
        history.append(
            {
                "step": step,
                "n_grad": sum(1 for r in step_rows if r.get("accepted_grad")),
                "n_fail": sum(1 for r in step_rows if not r.get("accepted_grad")),
                "mean_jerk_over_scale": mean_loss,
                "rows": step_rows,
            }
        )
        print(json.dumps({"step": step, "n_grad": history[-1]["n_grad"], "mean_jerk_over_scale": mean_loss}))

    # export updated weights in schema-2 shape
    weights = [p.detach().cpu().numpy().tolist() for p in net.parameters()]
    exported = {
        "schema_version": 2,
        "type": "regression",
        "output_mode": "single",
        "proposal_count": 1,
        "feature_spec": model.get("feature_spec"),
        "mean": mean.tolist(),
        "std": std.tolist(),
        "logfactor_bounds": [LOG_LO, LOG_HI],
        "residual_std": float(model.get("residual_std", 0.0)),
        "nfe": 1,
        "latent_quantiles": [0.0],
        "weights": weights,
        "metadata": {
            "training": "qp_trajectory_gradient_fd",
            "steps": steps,
            "lr": lr,
            "seed": seed,
            "lambda_T": 0.0,
            "j_scale": J_SCALE,
            "pack": str(pack_path),
            "init_model": str(init_model),
            "init_sha256": sha256(init_model),
            "pack_sha256": sha256(pack_path),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"timing_qp_seed{seed}.json"
    model_path.write_text(json.dumps(exported))
    hist_path = out_dir / f"train_history_seed{seed}.json"
    hist_path.write_text(json.dumps({"history": history}, indent=2))
    summary = {
        "model": str(model_path),
        "model_sha256": sha256(model_path),
        "history": str(hist_path),
        "final_mean_jerk_over_scale": history[-1]["mean_jerk_over_scale"] if history else None,
        "first_mean_jerk_over_scale": history[0]["mean_jerk_over_scale"] if history else None,
        "status": "passed"
        if history and history[-1]["n_grad"] > 0 and history[0]["mean_jerk_over_scale"] is not None
        and history[-1]["mean_jerk_over_scale"] is not None
        and history[-1]["mean_jerk_over_scale"] < history[0]["mean_jerk_over_scale"]
        else "failed",
    }
    (out_dir / f"train_summary_seed{seed}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if summary["status"] != "passed":
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pack = sub.add_parser("pack")
    p_pack.add_argument("--selected60", type=Path, required=True)
    p_pack.add_argument("--replay", type=Path, required=True)
    p_pack.add_argument("--out", type=Path, required=True)
    p_pack.add_argument("--n", type=int, default=16)
    p_train = sub.add_parser("train")
    p_train.add_argument("--pack", type=Path, required=True)
    p_train.add_argument("--init-model", type=Path, required=True)
    p_train.add_argument("--out-dir", type=Path, required=True)
    p_train.add_argument("--steps", type=int, default=100)
    p_train.add_argument("--lr", type=float, default=1e-3)
    p_train.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.cmd == "pack":
        build_pack(args.selected60, args.replay, args.out, args.n)
    else:
        train(args.pack, args.init_model, args.out_dir, args.steps, args.lr, args.seed)


if __name__ == "__main__":
    main()
