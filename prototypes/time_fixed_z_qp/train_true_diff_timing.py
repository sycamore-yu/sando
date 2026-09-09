#!/usr/bin/env python3
"""Phase E: train timing MLP with true Diff-QP (KKT) and optional λ_T * T.

L = J_traj / J_scale + lambda_T * T / T_scale
J_scale, T_scale computed from training pack only.
FD-proxy path kept as ablation (--grad fd); supervised init is the baseline.
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
    SINGLE_LOG_BOUNDS,
    load_model,
    normalize,
    raw_features,
)
from diff_time_qp_kkt import DiffTimeQP  # noqa: E402
from run_time_qp import build_spec, segment_dt, solve_hard_qp  # noqa: E402
from train_time_nn_qp import instance_from_pack_item, fd_dJ_df  # noqa: E402

F_MIN, F_MAX = 1.0, 2.5
LOG_LO, LOG_HI = SINGLE_LOG_BOUNDS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pack_scales(items):
    jerks, Ts = [], []
    for item in items:
        qp = instance_from_pack_item(item)
        f = float(item["factor_capture"])
        hard = solve_hard_qp(build_spec(qp, f), item["assignment"])
        if "jerk" not in hard:
            continue
        jerks.append(hard["jerk"])
        Ts.append(5.0 * segment_dt(qp["initial_dt"], qp["dc"], f))
    if not jerks:
        raise SystemExit("no feasible pack members for scales")
    return float(np.median(jerks)), float(np.median(Ts))


def train(
    pack_path: Path,
    init_model: Path,
    out_dir: Path,
    steps: int,
    lr: float,
    seed: int,
    lambda_t: float,
    grad_mode: str,
):
    pack = json.loads(pack_path.read_text())
    items = pack["items"]
    torch.manual_seed(seed)
    np.random.seed(seed)
    j_scale, t_scale = pack_scales(items)

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
        losses = []
        for idx in order:
            row = prepared[int(idx)]
            opt.zero_grad()
            log_f = torch.clamp(net(row["x"]), LOG_LO, LOG_HI)
            f = torch.exp(log_f)
            f_clamped = torch.clamp(f, F_MIN, F_MAX)
            # True Diff-QP path
            if grad_mode == "kkt":
                _x, jerk, ok = DiffTimeQP.apply(f_clamped, [row["qp"]], [row["assignment"]])
                if (not bool(torch.isfinite(jerk.detach()))) or float(ok.detach()) < 0.5:
                    step_rows.append(
                        {
                            "id": row["id"],
                            "status": "infeasible",
                            "f": float(f_clamped.detach()),
                        }
                    )
                    continue
                # T depends on f; attach analytic dT/df through tensor
                d0 = max(row["qp"]["initial_dt"], 2.0 * row["qp"]["dc"])
                T_t = 5.0 * d0 * f_clamped
                loss = jerk / j_scale + lambda_t * (T_t / t_scale)
                loss.backward()
                opt.step()
                step_rows.append(
                    {
                        "id": row["id"],
                        "status": "ok",
                        "f": float(f_clamped.detach()),
                        "jerk": float(jerk.detach()),
                        "T": float(T_t.detach()),
                        "loss": float(loss.detach()),
                        "grad_mode": "kkt",
                    }
                )
                losses.append(float(loss.detach()))
            else:
                # FD-proxy ablation: detach f, inject FD scalar grad
                f_val = float(f_clamped.detach())
                hard = solve_hard_qp(build_spec(row["qp"], f_val), row["assignment"])
                if "jerk" not in hard:
                    step_rows.append({"id": row["id"], "status": "infeasible", "f": f_val})
                    continue
                g = fd_dJ_df(row["qp"], row["assignment"], f_val)
                if g is None:
                    step_rows.append({"id": row["id"], "status": "fd_failed", "f": f_val})
                    continue
                d0 = max(row["qp"]["initial_dt"], 2.0 * row["qp"]["dc"])
                T_t = 5.0 * d0 * f_clamped
                jerk_proxy = f_clamped * 0.0 + hard["jerk"]
                # attach FD grad for jerk part
                jerk_t = f_clamped * torch.tensor(g, dtype=torch.float64) + (
                    hard["jerk"] - f_val * g
                )
                loss = jerk_t / j_scale + lambda_t * (T_t / t_scale)
                loss.backward()
                opt.step()
                step_rows.append(
                    {
                        "id": row["id"],
                        "status": "ok",
                        "f": f_val,
                        "jerk": hard["jerk"],
                        "T": float(T_t.detach()),
                        "loss": float(loss.detach()),
                        "grad_mode": "fd_proxy",
                        "fd_dJ_df": g,
                    }
                )
                losses.append(float(loss.detach()))
        history.append(
            {
                "step": step,
                "mean_loss": float(np.mean(losses)) if losses else None,
                "n_ok": len(losses),
                "n_fail": len(step_rows) - len(losses),
                "rows": step_rows,
            }
        )
        if step % 10 == 0 or step == steps - 1:
            print(
                json.dumps(
                    {
                        "step": step,
                        "mean_loss": history[-1]["mean_loss"],
                        "n_ok": history[-1]["n_ok"],
                        "n_fail": history[-1]["n_fail"],
                    }
                )
            )

    out_dir.mkdir(parents=True, exist_ok=True)
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
            "training": "true_diff_kkt" if grad_mode == "kkt" else "fd_proxy_ablation",
            "lambda_T": lambda_t,
            "j_scale": j_scale,
            "t_scale": t_scale,
            "steps": steps,
            "lr": lr,
            "seed": seed,
            "grad_mode": grad_mode,
            "init_model": str(init_model),
            "init_sha256": sha256(init_model),
            "pack": str(pack_path),
            "pack_sha256": sha256(pack_path),
        },
    }
    tag = f"{grad_mode}_lam{lambda_t}_seed{seed}"
    model_path = out_dir / f"timing_{tag}.json"
    hist_path = out_dir / f"history_{tag}.json"
    model_path.write_text(json.dumps(exported))
    hist_path.write_text(
        json.dumps(
            {
                "j_scale": j_scale,
                "t_scale": t_scale,
                "lambda_T": lambda_t,
                "grad_mode": grad_mode,
                "seed": seed,
                "history": history,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "model": str(model_path),
                "history": str(hist_path),
                "final_mean_loss": history[-1]["mean_loss"],
                "first_mean_loss": history[0]["mean_loss"],
            },
            indent=2,
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pack", type=Path, default=Path("evidence/train16_pack_geometry.json"))
    p.add_argument(
        "--init-model",
        type=Path,
        default=ROOT
        / "docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json",
    )
    p.add_argument("--out-dir", type=Path, default=Path("evidence/phase_e_train"))
    p.add_argument("--steps", type=int, default=50)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--lambda-t", type=float, default=0.0)
    p.add_argument("--grad", choices=("kkt", "fd"), default="kkt")
    args = p.parse_args()
    train(args.pack, args.init_model, args.out_dir, args.steps, args.lr, args.seed, args.lambda_t, args.grad)


if __name__ == "__main__":
    main()
