#!/usr/bin/env python3
"""Evaluate the captured SANDO objective through the vendored RAYEN map.

This is an experiment harness: each label is converted independently and no
expert target or cross-instance training is performed.
"""
import argparse
import json
import sys
import time
from pathlib import Path


def _substitute(expression, fixed):
    import numpy as np
    number = np.longdouble
    constant = number(expression.get("constant", 0.0))
    linear = []
    for term in expression.get("linear", []):
        if term["variable"] in fixed:
            constant += float(term["coefficient"]) * fixed[term["variable"]]
        else:
            linear.append((int(term["variable"]), number(term["coefficient"])))
    quadratic = []
    for term in expression.get("quadratic", []):
        first, second = int(term["first"]), int(term["second"])
        coefficient = number(term["coefficient"])
        if first in fixed and second in fixed:
            constant += coefficient * fixed[first] * fixed[second]
        elif first in fixed:
            linear.append((second, coefficient * fixed[first]))
        elif second in fixed:
            linear.append((first, coefficient * fixed[second]))
        else:
            quadratic.append((first, second, coefficient))
    return constant, linear, quadratic


def convert_fixed_model(instance, assignment):
    """Return dense six-variable linear constraints and the exact fixed objective."""
    model = instance["model"]
    fixed = {int(var): float(int(p == assignment[t]))
             for t, choices in enumerate(instance["assignment_variables"])
             for p, var in enumerate(choices)}
    variables = [item for item in model["variables"] if item["type"] == "C"]
    variables.sort(key=lambda item: int(item["id"]))
    ids = [int(item["id"]) for item in variables]
    if len(ids) != 6:
        raise ValueError("expected six continuous SANDO variables")
    index = {var: i for i, var in enumerate(ids)}
    rows = {"A_ub": [], "b_ub": [], "A_eq": [], "b_eq": []}
    for constraint in model["constraints"]:
        if constraint.get("indicator"):
            trigger = int(constraint["indicator_variable"])
            if trigger not in fixed:
                raise ValueError("indicator variable was not fixed")
            if fixed[trigger] != int(constraint["indicator_value"]):
                continue
        if constraint.get("quadratic"):
            raise ValueError("fixed model contains unsupported constraint")
        constant, terms, quadratic = _substitute(constraint["expression"], fixed)
        if quadratic:
            raise ValueError("fixed model contains quadratic constraint")
        row = [0.0] * 6
        for var, coefficient in terms:
            row[index[var]] += coefficient
        rhs = float(constraint["rhs"]) - constant
        sense = constraint["sense"]
        if not any(abs(value) > 1e-12 for value in row):
            if ((sense in ("<", 60) and rhs >= -1e-12) or
                    (sense in (">", 62) and rhs <= 1e-12) or
                    (sense in ("=", 61) and abs(rhs) <= 1e-12)):
                continue
            raise ValueError("fixed model is infeasible")
        if sense in ("<", 60): rows["A_ub"].append(row); rows["b_ub"].append(rhs)
        elif sense in (">", 62): rows["A_ub"].append([-x for x in row]); rows["b_ub"].append(-rhs)
        elif sense in ("=", 61): rows["A_eq"].append(row); rows["b_eq"].append(rhs)
        else: raise ValueError("unknown constraint sense")
    objective_constant, objective_terms, objective_quadratic = _substitute(model["objective"], fixed)
    import numpy as np
    objective = [np.longdouble(0.0)] * 6
    for var, coefficient in objective_terms:
        objective[index[var]] += coefficient
    bounds = [(float(item["lb"]), float(item["ub"])) for item in variables]
    for i, (lo, hi) in enumerate(bounds):
        if lo != -float("inf"):
            row = [0.0] * 6; row[i] = -1.0; rows["A_ub"].append(row); rows["b_ub"].append(-lo)
        if hi != float("inf"):
            row = [0.0] * 6; row[i] = 1.0; rows["A_ub"].append(row); rows["b_ub"].append(hi)
    return {**rows, "bounds": bounds, "objective": objective,
            "objective_constant": objective_constant, "variable_ids": ids,
            "objective_quadratic": objective_quadratic,
            "objective_sense": model.get("objective_sense", 1)}


def strict_relative_interior(converted):
    import numpy as np
    from scipy.optimize import linprog
    a_ub = np.asarray(converted["A_ub"], dtype=float).reshape((-1, 6))
    b_ub = np.asarray(converted["b_ub"], dtype=float)
    a_eq = np.asarray(converted["A_eq"], dtype=float).reshape((-1, 6))
    b_eq = np.asarray(converted["b_eq"], dtype=float)
    # Maximize a common slack for inequalities and finite bounds. Equalities
    # stay exact; scipy's presolve handles their affine hull correctly.
    rows, rhs = [], []
    for row, limit in zip(a_ub, b_ub): rows.append([*row, 1.0]); rhs.append(limit)
    for i, (lo, hi) in enumerate(converted["bounds"]):
        if lo != -float("inf"): rows.append([*(np.eye(6)[i] * -1), 1.0]); rhs.append(-lo)
        if hi != float("inf"): rows.append([*(np.eye(6)[i]), 1.0]); rhs.append(hi)
    result = linprog([0.0] * 6 + [-1.0], A_ub=np.asarray(rows) if rows else None,
                     b_ub=np.asarray(rhs) if rows else None,
                     A_eq=np.pad(a_eq, ((0, 0), (0, 1))) if a_eq.size else None,
                     b_eq=b_eq if a_eq.size else None,
                     bounds=[(None, None)] * 7, method="highs")
    if not result.success:
        return None, "infeasible_or_no_relative_interior"
    if result.x[-1] <= 1e-9:
        return result.x[:-1], "no_strict_relative_interior"
    return result.x[:-1], None


def objective_value(converted, x):
    import numpy as np
    value = converted["objective_constant"] + np.dot(converted["objective"], x)
    value += sum(coefficient * x[converted["variable_ids"].index(first)] * x[converted["variable_ids"].index(second)]
                 for first, second, coefficient in converted["objective_quadratic"])
    return float(value)


def objective_gradient(converted, x):
    gradient = list(converted["objective"])
    positions = {var: i for i, var in enumerate(converted["variable_ids"])}
    for first, second, coefficient in converted["objective_quadratic"]:
        gradient[positions[first]] += coefficient * x[positions[second]]
        gradient[positions[second]] += coefficient * x[positions[first]]
    return gradient


def centered_objective(converted, center):
    """Return q(center+z) in a numerically stable long-double expansion."""
    import numpy as np
    c = np.asarray(center, dtype=np.longdouble)
    if c.shape != (len(converted["variable_ids"]),):
        raise ValueError("objective center dimension mismatch")
    linear = np.asarray(converted["objective"], dtype=np.longdouble)
    quadratic = [(int(i), int(j), np.longdouble(v))
                 for i, j, v in converted["objective_quadratic"]]
    positions = {var: i for i, var in enumerate(converted["variable_ids"])}
    shifted_linear = linear.copy()
    constant = np.longdouble(converted["objective_constant"])
    for first, second, coefficient in quadratic:
        i, j = positions[first], positions[second]
        constant += coefficient * c[i] * c[j]
        shifted_linear[i] += coefficient * c[j]
        shifted_linear[j] += coefficient * c[i]
    constant += np.dot(linear, c)
    shifted = {"center": [float(v) for v in c],
               "constant": float(constant),
               "linear": [float(v) for v in shifted_linear],
               "quadratic": [(i, j, float(v)) for i, j, v in quadratic],
               "variable_ids": list(converted["variable_ids"]),
               "objective_constant": float(constant),
               "objective": [float(v) for v in shifted_linear],
               "objective_quadratic": [(i, j, float(v)) for i, j, v in quadratic]}
    return shifted


def residuals(converted, x):
    import numpy as np
    values = np.asarray(x, dtype=float)
    inequalities = np.asarray(converted["A_ub"], dtype=float).reshape((-1, 6))
    equalities = np.asarray(converted["A_eq"], dtype=float).reshape((-1, 6))
    return {"bounds": max((max(lo - values[i], values[i] - hi, 0.0)
                            for i, (lo, hi) in enumerate(converted["bounds"])), default=0.0),
            "linear": max(0.0, max((float(row @ values - limit) for row, limit in zip(inequalities, converted["b_ub"])), default=0.0)),
            "equalities": max((float(abs(row @ values - limit)) for row, limit in zip(equalities, converted["b_eq"])), default=0.0)}


def optimize_case(converted, steps=100, learning_rate=0.05, rayen_root=None):
    """Optimize one fixed objective through RAYEN and compare an unconstrained latent."""
    import numpy as np
    import torch
    if rayen_root:
        sys.path.insert(0, str(Path(rayen_root)))
    from rayen.constraints import LinearConstraint, ConvexConstraints
    from rayen.constraint_module import ConstraintModule
    a1 = np.asarray(converted["A_ub"], dtype=float).reshape((-1, 6))
    b1 = np.asarray(converted["b_ub"], dtype=float).reshape((-1, 1))
    a2 = np.asarray(converted["A_eq"], dtype=float).reshape((-1, 6))
    b2 = np.asarray(converted["b_eq"], dtype=float).reshape((-1, 1))
    interior, reason = strict_relative_interior(converted)
    if interior is None or reason:
        return {"skip_reason": reason or "no_relative_interior"}
    cs = ConvexConstraints(LinearConstraint(a1, b1, a2 if a2.size else None, b2 if b2.size else None),
                           y0=np.asarray(interior).reshape((-1, 1)), do_preprocessing_linear=False)
    centered = centered_objective(converted, np.asarray(interior, dtype=np.longdouble))
    previous_dtype = torch.get_default_dtype()
    try:
        torch.set_default_dtype(torch.float64)
        module = ConstraintModule(cs, create_map=False, method="RAYEN")
    finally:
        torch.set_default_dtype(previous_dtype)
    if not torch.equal(module.A_p, torch.as_tensor(cs.A_p, dtype=torch.float64)):
        raise RuntimeError("RAYEN constraint buffers lost precision")
    latent = torch.full((1, cs.n, 1), 0.1, dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.Adam([latent], lr=learning_rate)
    initial_point = module(latent).detach().numpy()[0, :, 0]
    initial = objective_value(converted, initial_point)
    trace = []
    best = float("inf")
    max_gradient_norm = 0.0
    started = time.perf_counter()
    for step in range(steps):
        optimizer.zero_grad()
        point = module(latent)[0, :, 0]
        value = objective_value_torch(centered, point - torch.as_tensor(centered["center"], dtype=point.dtype))
        if not torch.isfinite(point).all() or not torch.isfinite(value):
            raise RuntimeError(f"nonfinite RAYEN output at step {step}")
        value.backward()
        if latent.grad is None or not torch.isfinite(latent.grad).all():
            raise RuntimeError(f"nonfinite or missing latent gradient at step {step}")
        norm = float(torch.linalg.vector_norm(latent.grad).detach())
        max_gradient_norm = max(max_gradient_norm, norm)
        trace.append({"step": step, "raw_objective": float(value.detach()),
                      "latent_gradient_norm": norm, "residuals": residuals(converted, point.detach().numpy())})
        optimizer.step()
        best = min(best, float(value.detach()))
    final_point = module(latent).detach().numpy()[0, :, 0]
    objective_grad_norm = float(torch.linalg.vector_norm(torch.as_tensor(objective_gradient(converted, final_point), dtype=torch.float64)))
    return {"initial_raw_objective": initial, "final_raw_objective": objective_value(converted, final_point),
            "best_rayen_objective": best, "rayen_point": final_point.tolist(),
            "rayen_seconds": time.perf_counter() - started,
            "gradient_norm": max_gradient_norm, "objective_gradient_norm": objective_grad_norm,
            "initial_point": initial_point.tolist(), "trace": trace,
            "rayen_residuals": residuals(converted, final_point),
            "unconstrained_baseline": unconstrained_baseline(converted, initial_point, steps, learning_rate)}


def objective_value_torch(converted, x):
    import torch
    value = torch.as_tensor(converted.get("constant", converted.get("objective_constant")), dtype=x.dtype) + torch.dot(torch.as_tensor(converted.get("linear", converted.get("objective")), dtype=x.dtype), x)
    positions = {var: i for i, var in enumerate(converted["variable_ids"])}
    for first, second, coefficient in converted["objective_quadratic"]:
        value = value + coefficient * x[positions[first]] * x[positions[second]]
    return value


def unconstrained_baseline(converted, initial, steps=100, learning_rate=0.05):
    import torch
    latent = torch.tensor(initial, dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.Adam([latent], lr=learning_rate)
    for _ in range(steps):
        optimizer.zero_grad(); objective_value_torch(converted, latent).backward(); optimizer.step()
    point = latent.detach().tolist()
    return {"point": point, "raw_objective": objective_value(converted, point), "residuals": residuals(converted, point)}


def evaluate_labels(path, rayen_root=None, steps=100, limit=None):
    results = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if limit is not None and len(results) >= limit: break
        if not line.strip(): continue
        started = time.perf_counter()
        try:
            record = json.loads(line)
            instance = record["instance"]
            feasible = [candidate for candidate in record.get("candidates", []) if candidate.get("classification") == "feasible"]
            if not feasible: raise ValueError("no feasible candidate")
            chosen = min(feasible, key=lambda item: tuple(item["assignment"]))
            converted = convert_fixed_model(instance, chosen["assignment"])
            point, reason = strict_relative_interior(converted)
            item = {"line": line_number, "identity": {key: instance[key] for key in ("source_id", "config_id", "scene_id", "episode_id", "request_id", "factor_id")},
                    "qp_raw_objective": chosen["raw_objective"], "assignment": chosen["assignment"], "skip_reason": reason,
                    "conversion_seconds": time.perf_counter() - started}
            if point is not None: item["initial_raw_objective"] = objective_value(converted, point)
            if point is not None and rayen_root:
                item.update(optimize_case(converted, steps=steps, rayen_root=rayen_root))
            results.append(item)
        except Exception as error:
            results.append({"line": line_number, "skip_reason": str(error),
                            "conversion_seconds": time.perf_counter() - started})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rayen-root")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    Path(args.output).write_text("\n".join(json.dumps(item, allow_nan=False) for item in evaluate_labels(args.labels, args.rayen_root, args.steps, args.limit)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
