#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from evaluate_rayen_objective import (centered_objective, convert_fixed_model,
                                      objective_gradient, objective_value,
                                      strict_relative_interior)


def instance():
    variables = [{"id": i, "type": "C", "lb": -2.0, "ub": 2.0} for i in range(1, 7)]
    variables += [{"id": 10, "type": "B", "lb": 0.0, "ub": 1.0}]
    expression = lambda terms, constant=0.0: {"constant": constant, "linear": terms, "quadratic": []}
    return {"assignment_variables": [[10]], "model": {
        "variables": variables,
        "constraints": [{"expression": expression([{"variable": 1, "coefficient": 1.0}]), "sense": 60, "rhs": 1.0, "quadratic": False, "indicator": False},
                        {"expression": expression([{"variable": 2, "coefficient": 1.0}]), "sense": 60, "rhs": 0.5, "quadratic": False, "indicator": True, "indicator_variable": 10, "indicator_value": 1},
                        {"expression": expression([{"variable": 3, "coefficient": 1.0}]), "sense": 60, "rhs": -0.5, "quadratic": False, "indicator": True, "indicator_variable": 10, "indicator_value": 0}],
        "objective": {"constant": 3.0, "linear": [{"variable": 1, "coefficient": 2.0}],
                      "quadratic": [{"first": 1, "second": 1, "coefficient": 4.0}]},
        "objective_sense": 1}}


def main():
    converted = convert_fixed_model(instance(), [0])
    assert converted["variable_ids"] == [1, 2, 3, 4, 5, 6]
    assert 1.0 in converted["b_ub"] and 2.0 in converted["b_ub"]
    assert converted["objective_constant"] == 3.0
    assert objective_value(converted, [0.5] + [0.0] * 5) == 5.0
    x = [0.5] + [0.0] * 5
    h = 1e-6
    plus = x.copy(); plus[0] += h
    minus = x.copy(); minus[0] -= h
    assert abs((objective_value(converted, plus) - objective_value(converted, minus)) / (2 * h)
               - objective_gradient(converted, x)[0]) < 1e-5
    point, reason = strict_relative_interior(converted)
    assert reason is None and point is not None
    centered = centered_objective(converted, [0.25] + [0.0] * 5)
    for z in ([0.1] + [0.0] * 5, [-0.2] + [0.0] * 5):
        x2 = [0.25 + z[0]] + z[1:]
        assert abs(objective_value(converted, x2) - objective_value(centered, z)) < 1e-12
    # Indicator inactive rows must disappear, active rows must survive.
    converted_active = convert_fixed_model(instance(), [0])
    base = instance(); base["model"]["constraints"] = base["model"]["constraints"][:1]
    assert len(converted_active["A_ub"]) == len(convert_fixed_model(base, [0])["A_ub"]) + 1
    # Equality conversion must preserve an equality row for RAYEN's A2/b2.
    eq = instance(); eq["model"]["constraints"].append({"expression": {"constant": 0.0, "linear": [{"variable": 2, "coefficient": 1.0}], "quadratic": []}, "sense": 61, "rhs": 0.0, "quadratic": False, "indicator": False})
    converted_eq = convert_fixed_model(eq, [0])
    assert len(converted_eq["A_eq"]) == 1 and converted_eq["b_eq"] == [0.0]
    # Degenerate constant constraints are rejected when false.
    bad = instance(); bad["model"]["constraints"].append({"expression": {"constant": 0.0, "linear": [], "quadratic": []}, "sense": 60, "rhs": -1.0, "quadratic": False, "indicator": False})
    try:
        convert_fixed_model(bad, [0])
    except ValueError:
        pass
    else:
        raise AssertionError("infeasible constant constraint was accepted")
    print("rayen model conversion tests passed")


if __name__ == "__main__":
    main()
