#!/usr/bin/env python3
"""True differentiable fixed-C/fixed-Z time QP (Phase C).

Matrices that depend on factor f are built with torch ops, then passed into a
CvxpyLayer whose Parameters are those matrices. Gradients flow:

  f_tensor → {E,e,G,h,R,scales_inv} → QP → x*(f) → loss → ∂/∂f

FD central differences remain oracle-only (never the training path).

This does not claim Minvo-CP identity with Gurobi yet; it uses the same
node-basis QP as run_time_qp.py, with official sando.yaml default limits.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cvxpy as cp
import numpy as np
import torch
from cvxpylayers.torch import CvxpyLayer

from run_time_qp import (  # noqa: E402
    FD_SCALES,
    GRAD_ABS_TOL,
    GRAD_REL_TOL,
    RIDGE,
    SOLVER_ARGS,
    central_fd_dJ_df,
    load_planning_instance,
    planes_to_ab,
    segment_dt,
    solve_hard_qp,
    vector_matrix,
)

# Official sim defaults from config/sando.yaml (PlanningInstance pack omits them).
SANDO_DEFAULT_LIMITS = {"velocity": 5.0, "acceleration": 20.0, "jerk": 100.0}
SANDO_DEFAULT_JERK_WEIGHT = 10.0


def ensure_official_limits(instance: dict) -> dict:
    out = dict(instance)
    out.setdefault("limits", dict(SANDO_DEFAULT_LIMITS))
    out.setdefault("jerk_weight", SANDO_DEFAULT_JERK_WEIGHT)
    # Prefer explicit keys if present on raw packs later.
    for key, alias in (("v_max", "velocity"), ("a_max", "acceleration"), ("j_max", "jerk")):
        if key in out:
            out["limits"] = dict(out["limits"])
            out["limits"][alias] = float(out[key])
    if "jerk_smooth_weight" in out:
        out["jerk_weight"] = float(out["jerk_smooth_weight"])
    return out


def _basis_mats(duration: torch.Tensor, n_segments: int, dimension: int, device, dtype):
    """Build equality/inequality/jerk rows as torch tensors depending on duration."""
    t = duration
    pos = [
        torch.stack([torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype),
                     torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(1.0, device=device, dtype=dtype)]),
        torch.stack([torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype),
                     t / 3.0, torch.tensor(1.0, device=device, dtype=dtype)]),
        torch.stack([torch.tensor(0.0, device=device, dtype=dtype), t * t / 3.0, 2.0 * t / 3.0,
                     torch.tensor(1.0, device=device, dtype=dtype)]),
        torch.stack([t ** 3, t * t, t, torch.tensor(1.0, device=device, dtype=dtype)]),
    ]
    vel = [
        torch.stack([torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype),
                     torch.tensor(1.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype)]),
        torch.stack([torch.tensor(0.0, device=device, dtype=dtype), t, torch.tensor(1.0, device=device, dtype=dtype),
                     torch.tensor(0.0, device=device, dtype=dtype)]),
        torch.stack([3.0 * t * t, 2.0 * t, torch.tensor(1.0, device=device, dtype=dtype),
                     torch.tensor(0.0, device=device, dtype=dtype)]),
    ]
    acc = [
        torch.stack([torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(2.0, device=device, dtype=dtype),
                     torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype)]),
        torch.stack([6.0 * t, torch.tensor(2.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype),
                     torch.tensor(0.0, device=device, dtype=dtype)]),
    ]
    jerk = [
        torch.stack([torch.tensor(6.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype),
                     torch.tensor(0.0, device=device, dtype=dtype), torch.tensor(0.0, device=device, dtype=dtype)]),
    ]

    def coeff_row(n, axis, basis):
        row = torch.zeros(dimension, device=device, dtype=dtype)
        start = (3 * n + axis) * 4
        row[start : start + 4] = basis
        return row

    def vec_mat(n, basis):
        return torch.stack([coeff_row(n, axis, basis) for axis in range(3)])

    return pos, vel, acc, jerk, vec_mat


def build_torch_qp_mats(instance: dict, factor: torch.Tensor, assignment: list[int]):
    """Differentiable matrix construction for fixed-C/fixed-Z QP at factor."""
    instance = ensure_official_limits(instance)
    device, dtype = factor.device, factor.dtype
    n_segments, n_polys = instance["N"], instance["P"]
    d0 = max(float(instance["initial_dt"]), 2.0 * float(instance["dc"]))
    duration = d0 * factor
    dimension = 12 * n_segments
    pos, vel, acc, jerk, vec_mat = _basis_mats(duration, n_segments, dimension, device, dtype)

    x0 = torch.as_tensor(instance["x0"], device=device, dtype=dtype)
    xf = torch.as_tensor(instance["xf"], device=device, dtype=dtype)
    derivative_bases = (
        (pos[0], pos[3]),
        (vel[0], vel[2]),
        (acc[0], acc[1]),
    )

    eq_rows, eq_rhs = [], []
    for derivative, (start_basis, end_basis) in enumerate(derivative_bases):
        eq_rows.append(vec_mat(0, start_basis))
        eq_rhs.append(x0[3 * derivative : 3 * derivative + 3])
        eq_rows.append(vec_mat(n_segments - 1, end_basis))
        eq_rhs.append(xf[3 * derivative : 3 * derivative + 3])
    for n in range(n_segments - 1):
        for start_basis, end_basis in derivative_bases:
            eq_rows.append(vec_mat(n, end_basis) - vec_mat(n + 1, start_basis))
            eq_rhs.append(torch.zeros(3, device=device, dtype=dtype))
    E = torch.cat(eq_rows, dim=0)
    e = torch.cat(eq_rhs, dim=0)

    lower = torch.as_tensor(instance["map_lower"], device=device, dtype=dtype)
    upper = torch.as_tensor(instance["map_upper"], device=device, dtype=dtype)
    limits = instance["limits"]
    ineq_rows, ineq_rhs = [], []
    position_mats = []
    for n in range(n_segments):
        segment_positions = []
        for basis in pos:
            matrix = vec_mat(n, basis)
            segment_positions.append(matrix)
            for axis in range(3):
                ineq_rows.extend((matrix[axis], -matrix[axis]))
                ineq_rhs.extend((upper[axis], -lower[axis]))
        position_mats.append(segment_positions)
        for bases, limit in (
            (vel, float(limits["velocity"])),
            (acc, float(limits["acceleration"])),
            (jerk, float(limits["jerk"])),
        ):
            lim = torch.tensor(limit, device=device, dtype=dtype)
            for basis in bases:
                matrix = vec_mat(n, basis)
                for axis in range(3):
                    ineq_rows.extend((matrix[axis], -matrix[axis]))
                    ineq_rhs.extend((lim, lim))

    # Fixed-Z corridor faces (no Big-M).
    for n, layer in enumerate(instance["corridors"]):
        p = int(assignment[n])
        if not instance["valid"][n, p]:
            continue
        a = torch.as_tensor(layer[p]["A"], device=device, dtype=dtype)
        b = torch.as_tensor(layer[p]["b"], device=device, dtype=dtype)
        for face in range(a.shape[0]):
            normal = a[face]
            rhs = b[face]
            for matrix in position_mats[n]:
                ineq_rows.append(normal @ matrix)
                ineq_rhs.append(rhs)

    G = torch.stack(ineq_rows, dim=0)
    h = torch.stack(ineq_rhs, dim=0)

    R = torch.cat([vec_mat(n, jerk[0]) for n in range(n_segments)], dim=0)
    spans = torch.maximum(upper - lower, torch.ones(3, device=device, dtype=dtype))
    scale_parts = []
    for _ in range(n_segments):
        for span in spans:
            scale_parts.extend(
                (span / (duration ** 3), span / (duration ** 2), span / duration, span)
            )
    scales = torch.stack(scale_parts)
    scales_inv = 1.0 / scales
    return {
        "E": E,
        "e": e,
        "G": G,
        "h": h,
        "R": R,
        "scales_inv": scales_inv,
        "duration": duration,
        "T": n_segments * duration,
        "D": dimension,
        "weight": float(instance["jerk_weight"]),
    }


def build_diff_layer(shapes: dict, weight: float, ridge: float = RIDGE):
    D = shapes["D"]
    x = cp.Variable(D)
    E = cp.Parameter(shapes["E"])
    e = cp.Parameter(shapes["e"])
    G = cp.Parameter(shapes["G"])
    h = cp.Parameter(shapes["h"])
    R = cp.Parameter(shapes["R"])
    scales_inv = cp.Parameter(D)
    objective = weight * cp.sum_squares(R @ x) + ridge * cp.sum_squares(cp.multiply(scales_inv, x))
    problem = cp.Problem(cp.Minimize(objective), [E @ x == e, G @ x <= h])
    if not problem.is_dpp():
        raise RuntimeError("time QP layer is not DPP")
    return CvxpyLayer(problem, parameters=[E, e, G, h, R, scales_inv], variables=[x])


def solve_diff(layer, mats):
    (x_star,) = layer(
        mats["E"],
        mats["e"],
        mats["G"],
        mats["h"],
        mats["R"],
        mats["scales_inv"],
        solver_args=SOLVER_ARGS,
    )
    return x_star


def trajectory_jerk(mats, x_star):
    r = mats["R"] @ x_star
    return mats["weight"] * torch.sum(r * r)


def probe_autograd_vs_fd(instance, assignment, factor_value: float):
    instance = ensure_official_limits(instance)
    # Shape layer once from a numpy hard solve path for shapes (values unused).
    ref = build_torch_qp_mats(instance, torch.tensor(factor_value, dtype=torch.double), assignment)
    shapes = {
        "D": ref["D"],
        "E": tuple(ref["E"].shape),
        "e": tuple(ref["e"].shape),
        "G": tuple(ref["G"].shape),
        "h": tuple(ref["h"].shape),
        "R": tuple(ref["R"].shape),
    }
    layer = build_diff_layer(shapes, weight=ref["weight"])

    f = torch.tensor(factor_value, dtype=torch.double, requires_grad=True)
    mats = build_torch_qp_mats(instance, f, assignment)
    x_star = solve_diff(layer, mats)
    loss = trajectory_jerk(mats, x_star)
    loss.backward()
    auto = float(f.grad.detach())

    fd = {}
    for eps in FD_SCALES:
        g = central_fd_dJ_df(instance, assignment, factor_value, eps)
        fd[str(eps)] = g

    pairs = []
    scales = list(FD_SCALES)
    for a, b in zip(scales, scales[1:]):
        ga, gb = fd[str(a)], fd[str(b)]
        if ga is None or gb is None:
            pairs.append({"eps_a": a, "eps_b": b, "ok": False})
            continue
        denom = max(abs(ga), abs(gb), GRAD_ABS_TOL)
        pairs.append({"eps_a": a, "eps_b": b, "rel": abs(ga - gb) / denom, "ok": abs(ga - gb) / denom <= GRAD_REL_TOL})

    # Compare autograd to mid FD scale.
    mid = fd.get("0.0001")
    if mid is None:
        mid = next((v for v in fd.values() if v is not None), None)
    denom = max(abs(auto), abs(mid or 0.0), GRAD_ABS_TOL)
    rel_auto = None if mid is None else abs(auto - mid) / denom
    return {
        "factor": factor_value,
        "autograd_dJ_df": auto,
        "fd": fd,
        "fd_stable": sum(1 for p in pairs if p.get("ok")) >= 2,
        "autograd_vs_fd_rel": rel_auto,
        "autograd_vs_fd_ok": rel_auto is not None and rel_auto <= max(GRAD_REL_TOL * 5, 5e-2),
        "loss": float(loss.detach()),
        "forward_matches_hard": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        type=Path,
        default=Path("prototypes/time_fixed_z_qp/evidence/train16_pack_geometry.json"),
    )
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--factor", type=float, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("prototypes/time_fixed_z_qp/evidence/diff_time_qp_probe0.json"),
    )
    args = parser.parse_args()

    pack = json.loads(args.pack.read_text())
    item = pack["items"][args.index]
    raw = item["instance"]
    # Adapt PlanningInstance JSON → run_time_qp loader shape.
    tmp = Path("/tmp/diff_qp_instance.json")
    tmp.write_text(json.dumps(raw))
    # Minimal adapter: load_planning_instance expects corridors with planes.
    instance = {
        "path": str(tmp),
        "N": int(raw["n"]),
        "P": len(raw["corridors"][0]),
        "initial_dt": float(raw["initial_dt"]),
        "dc": float(raw["dc"]),
        "native_factor": float(raw["factor"]),
        "x0": np.asarray(raw["start"], dtype=float),
        "xf": np.asarray(raw["goal"], dtype=float),
        "map_lower": np.asarray([raw["map_bounds"][0], raw["map_bounds"][2], raw["map_bounds"][4]], dtype=float),
        "map_upper": np.asarray([raw["map_bounds"][1], raw["map_bounds"][3], raw["map_bounds"][5]], dtype=float),
        "limits": dict(SANDO_DEFAULT_LIMITS),
        "jerk_weight": SANDO_DEFAULT_JERK_WEIGHT,
        "corridors": [],
        "valid": np.zeros((int(raw["n"]), len(raw["corridors"][0])), dtype=bool),
    }
    for t, layer in enumerate(raw["corridors"]):
        polys = []
        for p, poly in enumerate(layer):
            a, b = planes_to_ab(poly["planes"])
            instance["valid"][t, p] = len(b) > 0 and bool(raw["valid_mask"][t][p])
            polys.append({"A": a, "b": b})
        instance["corridors"].append(polys)
    instance = ensure_official_limits(instance)

    assignment = item.get("assignment") or [0] * instance["N"]
    factor = float(args.factor if args.factor is not None else instance["native_factor"])

    hard = solve_hard_qp(
        __import__("run_time_qp", fromlist=["build_spec"]).build_spec(instance, factor),
        assignment,
    )
    report = probe_autograd_vs_fd(instance, assignment, factor)
    report["hard_status"] = hard.get("status")
    report["hard_jerk"] = hard.get("jerk")
    report["scene_id"] = item.get("scene_id")
    report["request_id"] = item.get("request_id")
    report["kind"] = "true_diff_time_qp_probe"
    report["training_path"] = "cvxpylayers_parameters_from_torch_f"
    report["fd_role"] = "oracle_only"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if hard.get("status") not in ("optimal", "optimal_inaccurate") and hard.get("jerk") is None:
        raise SystemExit("hard QP failed")
    if not report["autograd_vs_fd_ok"]:
        raise SystemExit("autograd vs FD failed")


if __name__ == "__main__":
    main()
