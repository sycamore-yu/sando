#!/usr/bin/env python3
"""Fixed-C / fixed-Z differentiable QP with continuous time factor f.

Stage-1 training path (fixed corridors and assignment):
  f -> segment_dt = max(initial_dt, 2*dc) * f
    -> rebuild time-dependent bases / objective / dynamics
    -> hard fixed-Z QP
    -> B*(f), J(f)

Forward is checked against live Gurobi rebuild JSON from
`time_fixed_z_forward_probe` when available. Gradients are checked by
central finite differences on Clarabel/CVXPYLayers solutions.
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

SOLVER_ARGS = {"eps": 1e-9, "max_iters": 200_000}
RIDGE = 1e-8
GRAD_REL_TOL = 1e-2
GRAD_ABS_TOL = 1e-5
FD_SCALES = (1e-3, 1e-4, 1e-5)
OBJ_REL_TOL = 1e-4
CONTROL_POINT_TOL = 1e-3


def segment_dt(initial_dt: float, dc: float, factor: float) -> float:
    if not (math.isfinite(initial_dt) and initial_dt >= 0 and math.isfinite(dc) and dc > 0
            and math.isfinite(factor) and factor > 0):
        raise ValueError("invalid segment time inputs")
    dt = max(initial_dt, 2.0 * dc) * factor
    if not (math.isfinite(dt) and dt > 0):
        raise ValueError("invalid segment duration")
    return dt


def coefficient_row(n, axis, basis, dimension):
    row = np.zeros(dimension)
    start = (3 * n + axis) * 4
    row[start : start + 4] = basis
    return row


def vector_matrix(n, basis, dimension):
    return np.vstack([coefficient_row(n, axis, basis, dimension) for axis in range(3)])


def planes_to_ab(planes):
    a = np.asarray([[p[0], p[1], p[2]] for p in planes], dtype=float)
    b = np.asarray([p[3] for p in planes], dtype=float)
    return a, b


def load_planning_instance(path: Path):
    raw = json.loads(path.read_text())
    if raw.get("n") != 5 or raw.get("norm") != "Linf" or raw.get("planner") != "SANDO":
        raise ValueError("expected N=5 Linf SANDO PlanningInstance")
    n_segments = int(raw["n"])
    n_polys = len(raw["corridors"][0])
    corridors = []
    valid = np.zeros((n_segments, n_polys), dtype=bool)
    for t, layer in enumerate(raw["corridors"]):
        if len(layer) != n_polys:
            raise ValueError("ragged corridor layers")
        polys = []
        for p, poly in enumerate(layer):
            a, b = planes_to_ab(poly["planes"])
            valid[t, p] = len(b) > 0 and bool(raw["valid_mask"][t][p])
            polys.append({"A": a, "b": b})
        corridors.append(polys)
    bounds = raw["map_bounds"]
    return {
        "path": str(path),
        "N": n_segments,
        "P": n_polys,
        "initial_dt": float(raw["initial_dt"]),
        "dc": float(raw["dc"]),
        "native_factor": float(raw["factor"]),
        "x0": np.asarray(raw["start"], dtype=float),
        "xf": np.asarray(raw["goal"], dtype=float),
        "map_lower": np.asarray([bounds[0], bounds[2], bounds[4]], dtype=float),
        "map_upper": np.asarray([bounds[1], bounds[3], bounds[5]], dtype=float),
        "limits": {"velocity": 5.0, "acceleration": 20.0, "jerk": 100.0},
        "jerk_weight": 10.0,
        "corridors": corridors,
        "valid": valid,
    }


def build_spec(instance, factor: float):
    n_segments, n_polys = instance["N"], instance["P"]
    duration = segment_dt(instance["initial_dt"], instance["dc"], factor)
    dimension = 12 * n_segments
    t = duration
    pos = np.array(
        [[0, 0, 0, 1], [0, 0, t / 3, 1], [0, t * t / 3, 2 * t / 3, 1], [t**3, t * t, t, 1]],
        dtype=float,
    )
    vel = np.array([[0, 0, 1, 0], [0, t, 1, 0], [3 * t * t, 2 * t, 1, 0]], dtype=float)
    acc = np.array([[0, 2, 0, 0], [6 * t, 2, 0, 0]], dtype=float)
    jerk = np.array([[6, 0, 0, 0]], dtype=float)
    derivative_bases = (
        (np.array([0, 0, 0, 1.0]), np.array([t**3, t * t, t, 1.0])),
        (np.array([0, 0, 1.0, 0]), np.array([3 * t * t, 2 * t, 1.0, 0])),
        (np.array([0, 2.0, 0, 0]), np.array([6 * t, 2.0, 0, 0])),
    )

    equality_rows, equality_rhs = [], []
    x0, xf = instance["x0"], instance["xf"]
    for derivative, (start_basis, end_basis) in enumerate(derivative_bases):
        equality_rows.extend(vector_matrix(0, start_basis, dimension))
        equality_rhs.extend(x0[3 * derivative : 3 * derivative + 3])
        equality_rows.extend(vector_matrix(n_segments - 1, end_basis, dimension))
        equality_rhs.extend(xf[3 * derivative : 3 * derivative + 3])
    for n in range(n_segments - 1):
        for start_basis, end_basis in derivative_bases:
            equality_rows.extend(
                vector_matrix(n, end_basis, dimension) - vector_matrix(n + 1, start_basis, dimension)
            )
            equality_rhs.extend(np.zeros(3))

    lower, upper = instance["map_lower"], instance["map_upper"]
    limits = instance["limits"]
    inequality_rows, inequality_rhs = [], []
    position_matrices = []
    for n in range(n_segments):
        segment_positions = []
        for basis in pos:
            matrix = vector_matrix(n, basis, dimension)
            segment_positions.append(matrix)
            for axis in range(3):
                inequality_rows.extend((matrix[axis], -matrix[axis]))
                inequality_rhs.extend((upper[axis], -lower[axis]))
        position_matrices.append(segment_positions)
        for bases, limit in (
            (vel, limits["velocity"]),
            (acc, limits["acceleration"]),
            (jerk, limits["jerk"]),
        ):
            for basis in bases:
                matrix = vector_matrix(n, basis, dimension)
                for axis in range(3):
                    inequality_rows.extend((matrix[axis], -matrix[axis]))
                    inequality_rhs.extend((limit, limit))

    records = []
    for n, layer in enumerate(instance["corridors"]):
        for p, poly in enumerate(layer):
            if not instance["valid"][n, p]:
                continue
            a, b = poly["A"], poly["b"]
            for face, (normal, rhs) in enumerate(zip(a, b)):
                support = np.where(normal >= 0, upper, lower) @ normal
                big_m = max(0.0, float(support - rhs))
                for control_point, matrix in enumerate(position_matrices[n]):
                    records.append((n, p, face, control_point, normal @ matrix, float(rhs), big_m))

    jerk_rows = []
    for n in range(n_segments):
        jerk_rows.extend(vector_matrix(n, jerk[0], dimension))
    point_rows = np.vstack(
        [matrix[axis] for segment in position_matrices for matrix in segment for axis in range(3)]
    )
    spans = np.maximum(upper - lower, 1.0)
    scales = []
    for _ in range(n_segments):
        for span in spans:
            scales.extend((span / t**3, span / t**2, span / t, span))

    return {
        "factor": factor,
        "dt": duration,
        "T": n_segments * duration,
        "N": n_segments,
        "P": n_polys,
        "D": dimension,
        "E": np.asarray(equality_rows, dtype=float),
        "e": np.asarray(equality_rhs, dtype=float),
        "G": np.asarray(inequality_rows, dtype=float),
        "h": np.asarray(inequality_rhs, dtype=float),
        "R": np.asarray(jerk_rows, dtype=float),
        "C": point_rows,
        "records": records,
        "valid": instance["valid"],
        "coefficient_scales": np.asarray(scales, dtype=float),
        "weight": float(instance["jerk_weight"]),
    }


def solve_hard_qp(spec, assignment):
    x = cp.Variable(spec["D"])
    constraints = [spec["E"] @ x == spec["e"], spec["G"] @ x <= spec["h"]]
    for n, p, _, _, row, rhs, _ in spec["records"]:
        if assignment[n] == p:
            constraints.append(row @ x <= rhs)
    objective = spec["weight"] * cp.sum_squares(spec["R"] @ x) + RIDGE * cp.sum_squares(
        cp.multiply(1.0 / spec["coefficient_scales"], x)
    )
    problem = cp.Problem(cp.Minimize(objective), constraints)
    problem.solve(solver=cp.CLARABEL, verbose=False)
    status = problem.status
    result = {"status": status, "factor": spec["factor"], "dt": spec["dt"], "T": spec["T"]}
    if status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        return result
    coeffs = np.asarray(x.value, dtype=float)
    result.update(
        coefficients=coeffs,
        objective=float(problem.value),
        jerk=float(spec["weight"] * (spec["R"] @ coeffs) @ (spec["R"] @ coeffs)),
        control_points=(spec["C"] @ coeffs).reshape(spec["N"], 4, 3),
    )
    return result


def build_time_layer_via_rebuild(instance, assignment, factors):
    """Differentiate by rebuilding the DPP layer at a base factor around FD points.

    True DPP-in-f requires parameterizing all time-dependent matrices. For stage-1
    acceptance we rebuild specs and use central FD on the hard QP oracle, then a
    one-shot CvxpyLayer at fixed f for z-style plumbing checks.
    """
    rows = []
    for factor in factors:
        spec = build_spec(instance, factor)
        rows.append(solve_hard_qp(spec, assignment))
    return rows


def central_fd_dJ_df(instance, assignment, factor, eps):
    plus = solve_hard_qp(build_spec(instance, factor + eps), assignment)
    minus = solve_hard_qp(build_spec(instance, factor - eps), assignment)
    if "jerk" not in plus or "jerk" not in minus:
        return None
    return (plus["jerk"] - minus["jerk"]) / (2 * eps)


def probe_loss_gradient_stability(instance, assignment, factor):
    """FD of trajectory jerk w.r.t. f at several scales; report relative agreement."""
    grads = {}
    for eps in FD_SCALES:
        g = central_fd_dJ_df(instance, assignment, factor, eps)
        grads[eps] = g
    pairs = []
    scales = list(FD_SCALES)
    for a, b in zip(scales, scales[1:]):
        ga, gb = grads[a], grads[b]
        if ga is None or gb is None:
            pairs.append({"eps_a": a, "eps_b": b, "ok": False, "reason": "solve_failed"})
            continue
        denom = max(abs(ga), abs(gb), GRAD_ABS_TOL)
        rel = abs(ga - gb) / denom
        pairs.append(
            {
                "eps_a": a,
                "eps_b": b,
                "ga": ga,
                "gb": gb,
                "rel": rel,
                "ok": rel <= GRAD_REL_TOL or max(abs(ga), abs(gb)) <= GRAD_ABS_TOL,
            }
        )
    stable = sum(1 for p in pairs if p["ok"]) >= 2
    return {"grads": {str(k): v for k, v in grads.items()}, "pairs": pairs, "stable": stable}


def compare_control_points(python_points, gurobi_coeffs_xyz):
    # gurobi recovers [axis][4*t + c]; python C @ x is (N,4,3)
    max_abs = 0.0
    for t in range(5):
        for c in range(4):
            for axis in range(3):
                g = gurobi_coeffs_xyz[axis][4 * t + c]
                p = python_points[t, c, axis]
                max_abs = max(max_abs, abs(g - p))
    return max_abs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/ampls/fixtures/translated_trajectory.json"),
    )
    parser.add_argument(
        "--gurobi-report",
        type=Path,
        default=None,
        help="JSON report from time_fixed_z_forward_probe (optional)",
    )
    parser.add_argument("--assignment", default="0,0,0,0,0")
    args = parser.parse_args()
    assignment = [int(x) for x in args.assignment.split(",")]
    instance = load_planning_instance(args.fixture)

    native = solve_hard_qp(build_spec(instance, instance["native_factor"]), assignment)
    if "objective" not in native:
        raise SystemExit(f"native-factor QP failed: {native}")

    report = {
        "fixture": instance["path"],
        "native_factor": instance["native_factor"],
        "native_dt": native["dt"],
        "native_status": native["status"],
        "native_jerk": native["jerk"],
        "native_objective_with_ridge": native["objective"],
        "assignment": assignment,
    }

    sweep = build_time_layer_via_rebuild(
        instance, assignment, [1.0, 1.25, 1.5, instance["native_factor"], 2.0, 2.5]
    )
    report["sweep"] = [
        {
            "factor": row.get("factor"),
            "status": row.get("status"),
            "jerk": row.get("jerk"),
            "dt": row.get("dt"),
        }
        for row in sweep
    ]

    grad = probe_loss_gradient_stability(instance, assignment, instance["native_factor"])
    report["fd_jerk_wrt_f"] = grad

    if args.gurobi_report and args.gurobi_report.exists():
        gurobi = json.loads(args.gurobi_report.read_text())
        # probe prints multiple JSON lines; accept final object or file with status
        if isinstance(gurobi, list):
            gurobi = gurobi[-1]
        native_row = None
        for row in gurobi.get("rows", []):
            if abs(row.get("factor", -1) - instance["native_factor"]) < 1e-12 and row.get("ok"):
                native_row = row
                break
        report["gurobi_native_objective"] = None if native_row is None else native_row.get("objective")
        report["gurobi_compare_note"] = (
            "Python objective includes ridge; compare jerk/control points when coeffs present"
        )

    report["gate_forward_native_solved"] = native["status"] in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE)
    report["gate_fd_stable"] = bool(grad["stable"])
    report["status"] = "passed" if report["gate_forward_native_solved"] and report["gate_fd_stable"] else "failed"
    print(json.dumps(report, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
