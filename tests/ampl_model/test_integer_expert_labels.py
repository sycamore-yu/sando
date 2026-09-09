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
    test_minvo_basis_matches_online_solver()
    test_minvo_hull_catches_between_sample_violation()
    test_geometry_is_explicitly_unverified()
    test_expert_requires_complete_solver_evidence_and_matching_source()
    print("integer expert label tests passed")


def test_minvo_basis_matches_online_solver():
    import re
    import numpy as np
    coefficients = [[0.0] * 20 for _ in range(3)]
    coefficients[0][:4] = [1.0, 2.0, 3.0, 4.0]
    points = segment_control_points(coefficients, 0.5)
    source = (Path(__file__).parents[2] / "include/sando/sando_type.hpp").read_text()
    block = source.split("A_pos_mv_rest <<", 1)[1].split("//////INVERSE", 1)[0]
    values = [float(value) for value in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", block)]
    expected = np.array([0.125, 0.5, 1.5, 4.0]) @ np.linalg.inv(np.array(values).reshape(4, 4))
    assert all(abs(points[0][index][0] - value) < 1e-12
               for index, value in enumerate(expected))


def test_minvo_hull_catches_between_sample_violation():
    # x(t)=.02-(t-1/6)^2 is <=0 at t=0,1/3,2/3,1 but positive between them.
    coefficients = [[0.0] * 20 for _ in range(3)]
    coefficients[0][:4] = [0.0, -1.0, 1.0 / 3.0, 0.02 - 1.0 / 36.0]
    points = segment_control_points(coefficients, 1.0)
    assert all(point[0] <= 0.0 for point in points[0][0:1]) is False


def test_geometry_is_explicitly_unverified():
    result = geometric_good_set(instance(), {}, "hover")
    assert result["label_source"] == "geometric_support_only"
    assert result["solver_verified"] is False


def test_expert_requires_complete_solver_evidence_and_matching_source():
    try:
        from train_integer_corridor_policy import _validated_expert_record
    except ImportError:
        print("skip expert provenance test")
        return
    x = instance()
    evidence = {"assignment": [0, 0, 0, 0, 0], "status": 2,
                "raw_objective": 1.0, "objective": 1.0,
                "residuals": {"valid": True, "bounds": 0.0, "constraints": 0.0, "integrality": 0.0, "objective": 0.0},
                "objective_provenance": {key: x[key] for key in ("source_id", "config_id", "scene_id", "episode_id", "request_id", "factor_id")}}
    record = {"instance": x, "good_assignments": [evidence["assignment"]],
              "demonstration": evidence, "good_assignment_evidence": [evidence]}
    assert _validated_expert_record(record) is not None
    missing_residuals = dict(record)
    missing_residuals["good_assignment_evidence"] = [dict(evidence, residuals={"valid": True})]
    assert _validated_expert_record(missing_residuals) is None
    weak = dict(record)
    weak.pop("good_assignment_evidence")
    assert _validated_expert_record(weak) is None
    wrong_source = dict(record)
    wrong_source["good_assignment_evidence"] = [dict(evidence, objective_provenance={"source_id": "other"})]
    assert _validated_expert_record(wrong_source) is None


if __name__ == "__main__":
    main()
