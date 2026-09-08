#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_set_supervision import (
    assignments_from_mask,
    effective_polytope_mask,
    expert_demo_record,
    geometric_good_set,
    recover_numeric_coefficients,
    segment_control_points,
)


def instance():
    corridors = []
    mask = []
    for _ in range(5):
        corridors.append([
            {"planes": [[1.0, 0.0, 0.0, 2.0], [-1.0, 0.0, 0.0, 2.0], [0.0, 1.0, 0.0, 2.0], [0.0, -1.0, 0.0, 2.0], [0.0, 0.0, 1.0, 4.0], [0.0, 0.0, -1.0, 0.0]]},
            {"planes": [[1.0, 0.0, 0.0, 6.0], [-1.0, 0.0, 0.0, -2.5], [0.0, 1.0, 0.0, 2.0], [0.0, -1.0, 0.0, 2.0], [0.0, 0.0, 1.0, 4.0], [0.0, 0.0, -1.0, 0.0]]},
        ])
        mask.append([True, True])
    coefficients = []
    for axis, value in enumerate((0.0, 0.0, 2.0)):
        axis_coeff = []
        for _ in range(5):
            axis_coeff.extend([
                {"constant": 0.0, "linear": [], "quadratic": []},
                {"constant": 0.0, "linear": [], "quadratic": []},
                {"constant": 0.0, "linear": [], "quadratic": []},
                {"constant": value, "linear": [], "quadratic": []},
            ])
        coefficients.append(axis_coeff)
    return {
        "schema_version": 1, "n": 5, "norm": "Linf", "planner": "SANDO",
        "factor": 1.0, "initial_dt": 0.2, "dc": 0.05, "segment_dt": 0.2,
        "start": [0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "goal": [0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "map_bounds": [-4.0, 8.0, -4.0, 4.0, 0.0, 4.0],
        "corridors": corridors, "valid_mask": mask, "assignment_variables": [[1, 2]] * 5,
        "coefficients": coefficients,
        "outcome": {"capture": {"split": "train", "capture_round": 0}},
        "scene_id": "unknown_dynamic-n50-d0.65-seed0",
        "episode_id": "e", "request_id": "r", "factor_id": "0", "source_id": "s", "config_id": "c",
    }


def main():
    x = instance()
    values = {}
    coefficients = recover_numeric_coefficients(x, values)
    points = segment_control_points(coefficients, x["segment_dt"])
    assert points[0][0] == [0.0, 0.0, 2.0]
    mask = effective_polytope_mask(x, points)
    assert mask[0][0] is True
    assert mask[0][1] is False
    good = assignments_from_mask(mask)
    assert good == [(0, 0, 0, 0, 0)]
    geometric = geometric_good_set(x, values, "hover")
    demo = expert_demo_record(x, {"assignment": [0, 0, 0, 0, 0], "status": "feasible_relative_to_expert",
                                  "raw_objective": 1.0, "source": "geometric_support"},
                              geometric["good_assignments"])
    assert demo["record_purpose"] == "expert_demo"
    assert demo["costs_complete"] is False
    unsolved = [item for item in demo["candidates"] if item["classification"] == "not_solved"]
    assert len(unsolved) == 31
    print("integer expert label tests passed")


if __name__ == "__main__":
    main()
