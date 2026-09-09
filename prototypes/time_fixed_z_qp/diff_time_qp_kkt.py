#!/usr/bin/env python3
"""True Diff-QP via active-set KKT implicit differentiation (Phase C).

Forward: Clarabel hard fixed-C/fixed-Z QP (same as run_time_qp.solve_hard_qp).
Backward: differentiate the active KKT system w.r.t. factor f.

CvxpyLayer(full matrix Parameters) was measured wrong vs same-solver FD
(~6% on jerk, ~79% on v·x); do not use that path for training claims.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.autograd import Function

from run_time_qp import (
    FD_SCALES,
    GRAD_ABS_TOL,
    GRAD_REL_TOL,
    build_spec,
    central_fd_dJ_df,
    planes_to_ab,
    solve_hard_qp,
)

SANDO_DEFAULT_LIMITS = {"velocity": 5.0, "acceleration": 20.0, "jerk": 100.0}
SANDO_DEFAULT_JERK_WEIGHT = 10.0
ACTIVE_TOL = 1e-6


def ensure_official_limits(instance: dict) -> dict:
    out = dict(instance)
    out.setdefault("limits", dict(SANDO_DEFAULT_LIMITS))
    out.setdefault("jerk_weight", SANDO_DEFAULT_JERK_WEIGHT)
    return out


def instance_from_pack_item(item: dict) -> tuple[dict, list[int]]:
    raw = item["instance"]
    n, pcount = int(raw["n"]), len(raw["corridors"][0])
    instance = {
        "path": item.get("scene_id", ""),
        "N": n,
        "P": pcount,
        "initial_dt": float(raw["initial_dt"]),
        "dc": float(raw["dc"]),
        "native_factor": float(raw["factor"]),
        "x0": np.asarray(raw["start"], dtype=float),
        "xf": np.asarray(raw["goal"], dtype=float),
        "map_lower": np.asarray(
            [raw["map_bounds"][0], raw["map_bounds"][2], raw["map_bounds"][4]], dtype=float
        ),
        "map_upper": np.asarray(
            [raw["map_bounds"][1], raw["map_bounds"][3], raw["map_bounds"][5]], dtype=float
        ),
        "limits": dict(SANDO_DEFAULT_LIMITS),
        "jerk_weight": SANDO_DEFAULT_JERK_WEIGHT,
        "corridors": [],
        "valid": np.zeros((n, pcount), dtype=bool),
    }
    for t, layer in enumerate(raw["corridors"]):
        polys = []
        for p, poly in enumerate(layer):
            a, b = planes_to_ab(poly["planes"])
            instance["valid"][t, p] = len(b) > 0 and bool(raw["valid_mask"][t][p])
            polys.append({"A": a, "b": b})
        instance["corridors"].append(polys)
    assignment = list(item.get("assignment") or [0] * n)
    return ensure_official_limits(instance), assignment


def _qp_data(spec: dict, assignment: list[int]):
    """Return Q, c=0, E, e, G, h for min x'Qx s.t. Ex=e, Gx<=h (jerk + ridge)."""
    R = spec["R"]
    scales = spec["coefficient_scales"]
    w = float(spec["weight"])
    # loss = w ||Rx||^2 + ridge ||x/scales||^2  => Q = w R^T R + ridge diag(1/s^2)
    # torch/cvx use sum_squares without 1/2, so gradient 2Qx matches if Q as below for KKT of
    # ∇(x' Q x) = 2 Q x when Q symmetric. Use Q = w R^T R + ridge S.
    from run_time_qp import RIDGE

    S = np.diag(1.0 / (scales ** 2))
    Q = w * (R.T @ R) + RIDGE * S
    E, e = spec["E"], spec["e"]
    G_rows, h_rows = [spec["G"]], [spec["h"]]
    for n, p, _, _, row, rhs, _ in spec["records"]:
        if assignment[n] == p:
            G_rows.append(row.reshape(1, -1))
            h_rows.append(np.array([rhs]))
    G = np.vstack(G_rows)
    h = np.concatenate(h_rows)
    return Q, E, e, G, h


def _active_kkt_solve_dxdf(spec, assignment, x, dspec_plus, dspec_minus, eps):
    """Central-difference the KKT residual and solve active KKT for dx/df."""
    Q, E, e, G, h = _qp_data(spec, assignment)
    slack = h - G @ x
    active = slack <= ACTIVE_TOL
    Ga = G[active]
    # Stationarity multipliers via least squares on active KKT.
    # [2Q  E' Ga'] [x; y; z] ≈ 0 for unconstrained optimum of Lagrangian; use solve:
    D = Q.shape[0]
    ne, na = E.shape[0], Ga.shape[0]
    K = np.zeros((D + ne + na, D + ne + na))
    K[:D, :D] = 2.0 * Q
    K[:D, D : D + ne] = E.T
    K[:D, D + ne :] = Ga.T
    K[D : D + ne, :D] = E
    K[D + ne :, :D] = Ga
    rhs = np.zeros(D + ne + na)
    rhs[:D] = 0.0  # 2Qx + E'y + Ga'z = 0
    # Solve for multipliers given x: K_yz @ [y;z] = -2Qx with x fixed
    # Better: full Newton residual at solution should be ~0.
    try:
        yz = np.linalg.lstsq(K[:D, D:], -2.0 * Q @ x, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    y, z = yz[:ne], yz[ne:]

    # Differentiate KKT: d(2Qx)/df + 2Q dx/df + E'^T dy + Ga'^T dz + dE'^T y + dGa'^T z = 0
    # E dx/df + dE x = de/df
    # Ga dx/df + dGa x = dha/df
    Qp, Ep, ep, Gp, hp = _qp_data(dspec_plus, assignment)
    Qm, Em, em, Gm, hm = _qp_data(dspec_minus, assignment)
    dQ = (Qp - Qm) / (2 * eps)
    dE = (Ep - Em) / (2 * eps)
    de = (ep - em) / (2 * eps)
    dG = (Gp - Gm) / (2 * eps)
    dh = (hp - hm) / (2 * eps)
    dGa = dG[active]
    dha = dh[active]

    rhs_x = -(2.0 * dQ @ x + dE.T @ y + dGa.T @ z)
    rhs_e = de - dE @ x
    rhs_a = dha - dGa @ x
    rhs_full = np.concatenate([rhs_x, rhs_e, rhs_a])
    try:
        sol = np.linalg.solve(K, rhs_full)
    except np.linalg.LinAlgError:
        sol = np.linalg.lstsq(K, rhs_full, rcond=None)[0]
    return sol[:D]


class DiffTimeQP(Function):
    @staticmethod
    def forward(ctx, factor, instance_ref, assignment_ref):
        # instance_ref / assignment_ref stored as plain Python via ctx
        f = float(factor.detach().cpu().item())
        instance = instance_ref[0]
        assignment = assignment_ref[0]
        spec = build_spec(instance, f)
        hard = solve_hard_qp(spec, assignment)
        if "coefficients" not in hard:
            # Return zeros; mark failed
            x = torch.zeros(spec["D"], dtype=factor.dtype)
            ctx.failed = True
            ctx.save_for_backward(factor)
            ctx.spec = spec
            ctx.assignment = assignment
            ctx.instance = instance
            ctx.x_np = np.zeros(spec["D"])
            return x, torch.tensor(float("nan"), dtype=factor.dtype), torch.tensor(0.0, dtype=factor.dtype)
        x_np = hard["coefficients"]
        jerk = hard["jerk"]
        ctx.failed = False
        ctx.save_for_backward(factor)
        ctx.spec = spec
        ctx.assignment = assignment
        ctx.instance = instance
        ctx.x_np = x_np
        ctx.weight = float(spec["weight"])
        ctx.R = spec["R"]
        return (
            torch.as_tensor(x_np, dtype=factor.dtype),
            torch.tensor(jerk, dtype=factor.dtype),
            torch.tensor(1.0, dtype=factor.dtype),
        )

    @staticmethod
    def backward(ctx, grad_x, grad_jerk, grad_ok):
        if ctx.failed:
            return torch.zeros_like(ctx.saved_tensors[0]), None, None
        (factor,) = ctx.saved_tensors
        f = float(factor.detach().cpu().item())
        # Choose eps for differentiating QP data
        eps = 1e-4
        spec_p = build_spec(ctx.instance, f + eps)
        spec_m = build_spec(ctx.instance, f - eps)
        dxdf = _active_kkt_solve_dxdf(ctx.spec, ctx.assignment, ctx.x_np, spec_p, spec_m, eps)
        if dxdf is None:
            return torch.zeros_like(factor), None, None
        # d(jerk)/df = 2 w (R x)' ( (dR/df) x + R dx/df )
        R = ctx.R
        Rp = spec_p["R"]
        Rm = spec_m["R"]
        dR = (Rp - Rm) / (2 * eps)
        x = ctx.x_np
        w = ctx.weight
        dj_df = 2.0 * w * (R @ x) @ (dR @ x + R @ dxdf)
        g = 0.0
        if grad_x is not None:
            g += float(np.asarray(grad_x.detach().cpu(), dtype=float) @ dxdf)
        if grad_jerk is not None:
            g += float(grad_jerk.detach().cpu().item()) * dj_df
        grad_f = torch.tensor(g, dtype=factor.dtype, device=factor.device).reshape_as(factor)
        return grad_f, None, None


def diff_solve(instance, assignment, factor_tensor):
    # Wrap python objects for autograd Function (not differentiated).
    return DiffTimeQP.apply(factor_tensor, [instance], [assignment])


def probe(instance, assignment, factor_value: float):
    f = torch.tensor(factor_value, dtype=torch.double, requires_grad=True)
    x, jerk, ok = diff_solve(instance, assignment, f)
    if not torch.isfinite(jerk):
        return {"ok": False, "reason": "forward_failed"}
    jerk.backward()
    auto = float(f.grad.detach())
    fd = {str(eps): central_fd_dJ_df(instance, assignment, factor_value, eps) for eps in FD_SCALES}
    mid = fd.get("0.0001")
    denom = max(abs(auto), abs(mid or 0.0), GRAD_ABS_TOL)
    rel = None if mid is None else abs(auto - mid) / denom
    # Solution probe
    f2 = torch.tensor(factor_value, dtype=torch.double, requires_grad=True)
    x2, _, _ = diff_solve(instance, assignment, f2)
    torch.manual_seed(0)
    v = torch.randn_like(x2)
    (v * x2).sum().backward()
    auto_v = float(f2.grad.detach())

    def Lv(fv):
        spec = build_spec(instance, fv)
        hard = solve_hard_qp(spec, assignment)
        if "coefficients" not in hard:
            return None
        return float(np.asarray(v.detach().cpu()) @ hard["coefficients"])

    fd_v = {}
    for eps in FD_SCALES:
        a, b = Lv(factor_value + eps), Lv(factor_value - eps)
        fd_v[str(eps)] = None if a is None or b is None else (a - b) / (2 * eps)
    mid_v = fd_v.get("0.0001")
    denom_v = max(abs(auto_v), abs(mid_v or 0.0), GRAD_ABS_TOL)
    rel_v = None if mid_v is None else abs(auto_v - mid_v) / denom_v
    return {
        "ok": True,
        "factor": factor_value,
        "jerk": float(jerk.detach()),
        "autograd_dJ_df": auto,
        "fd_dJ_df": fd,
        "autograd_vs_fd_rel": rel,
        "autograd_vs_fd_ok": rel is not None and rel <= max(GRAD_REL_TOL, 0.05),
        "solution_probe_autograd": auto_v,
        "solution_probe_fd": fd_v,
        "solution_probe_rel": rel_v,
        "solution_probe_ok": rel_v is not None and rel_v <= max(GRAD_REL_TOL, 0.05),
        "training_path": "active_set_kkt_implicit_diff",
        "fd_role": "oracle_only",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        type=Path,
        default=Path("evidence/train16_pack_geometry.json"),
    )
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("evidence/diff_time_qp_kkt_probe0.json"))
    args = parser.parse_args()
    pack = json.loads(args.pack.read_text())
    instance, assignment = instance_from_pack_item(pack["items"][args.index])
    factor = float(instance["native_factor"])
    report = probe(instance, assignment, factor)
    report["scene_id"] = pack["items"][args.index].get("scene_id")
    report["request_id"] = pack["items"][args.index].get("request_id")
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report.get("autograd_vs_fd_ok"):
        raise SystemExit("KKT autograd vs FD failed")


if __name__ == "__main__":
    main()
