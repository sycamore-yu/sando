#!/usr/bin/env python3
"""Prove time parameter updates from trajectory cost through fixed-C/fixed-Z QP.

Three matched runs (same init, same inputs, lambda_T=0):
  1) frozen_f — no updates
  2) stop_grad — loss uses explicit T only (here 0), so no trajectory gradient
  3) full_qp — scalar f updated by central-FD dJ/df through the hard QP

Gate: full_qp must change f and reduce jerk; frozen/stop_grad must not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_time_qp import build_spec, load_planning_instance, solve_hard_qp, segment_dt

F_MIN, F_MAX = 1.0, 2.5


def clamp_f(value: float) -> float:
    return float(min(F_MAX, max(F_MIN, value)))


def solve_jerk(instance, assignment, factor: float):
    result = solve_hard_qp(build_spec(instance, factor), assignment)
    if "jerk" not in result:
        return None, result
    return float(result["jerk"]), result


def fd_grad(instance, assignment, factor: float, eps: float = 1e-4):
    plus, _ = solve_jerk(instance, assignment, clamp_f(factor + eps))
    minus, _ = solve_jerk(instance, assignment, clamp_f(factor - eps))
    if plus is None or minus is None:
        return None
    return (plus - minus) / (2 * eps)


def run_arm(name, instance, assignment, f0, steps, lr, use_traj_grad: bool):
    f = float(f0)
    history = []
    for step in range(steps):
        jerk, raw = solve_jerk(instance, assignment, f)
        row = {
            "step": step,
            "f": f,
            "T": 5 * segment_dt(instance["initial_dt"], instance["dc"], f),
            "jerk": jerk,
            "status": raw.get("status"),
        }
        if jerk is None:
            row["updated"] = False
            history.append(row)
            break
        if use_traj_grad:
            g = fd_grad(instance, assignment, f)
            row["dJ_df"] = g
            if g is None:
                row["updated"] = False
                history.append(row)
                break
            f = clamp_f(f - lr * g)
            row["updated"] = True
        else:
            row["dJ_df"] = 0.0
            row["updated"] = False
        history.append(row)
    return {"name": name, "history": history, "final_f": f, "final_jerk": history[-1].get("jerk")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("../../tests/ampls/fixtures/translated_trajectory.json"))
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-7)
    parser.add_argument("--f0", type=float, default=2.0)
    args = parser.parse_args()

    # Allow running from repo root or package dir.
    fixture = args.fixture
    if not fixture.exists():
        fixture = Path("tests/ampls/fixtures/translated_trajectory.json")
    instance = load_planning_instance(fixture.resolve() if fixture.exists() else Path("tests/ampls/fixtures/translated_trajectory.json"))
    # Prefer repo-relative when invoked from prototypes/time_fixed_z_qp
    if not Path(instance["path"]).exists():
        instance = load_planning_instance(Path(__file__).resolve().parents[2] / "tests/ampls/fixtures/translated_trajectory.json")

    assignment = [0, 0, 0, 0, 0]
    f0 = clamp_f(args.f0)
    frozen = run_arm("frozen_f", instance, assignment, f0, args.steps, args.lr, False)
    stop = run_arm("stop_grad", instance, assignment, f0, args.steps, args.lr, False)
    full = run_arm("full_qp", instance, assignment, f0, args.steps, args.lr, True)

    j0 = frozen["history"][0]["jerk"]
    gate = {
        "frozen_unchanged": abs(frozen["final_f"] - f0) < 1e-12,
        "stop_unchanged": abs(stop["final_f"] - f0) < 1e-12,
        "full_moved": abs(full["final_f"] - f0) > 1e-6,
        "full_jerk_improved": full["final_jerk"] is not None and j0 is not None and full["final_jerk"] < j0 - 1e-3,
        "same_init_jerk": abs((frozen["history"][0]["jerk"] or 0) - (full["history"][0]["jerk"] or 0)) < 1e-6,
    }
    report = {
        "f0": f0,
        "steps": args.steps,
        "lr": args.lr,
        "lambda_T": 0.0,
        "arms": {"frozen_f": frozen, "stop_grad": stop, "full_qp": full},
        "gates": gate,
        "status": "passed" if all(gate.values()) else "failed",
    }
    print(json.dumps(report, indent=2))
    out = Path(__file__).resolve().parent / "data" / "train_smoke_report.json"
    out.write_text(json.dumps(report, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
