#!/usr/bin/env python3
"""Standalone checks for reconstructable request snapshots and time queries."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from reconstructable_request import (
    from_planning_instance,
    missing_observation_fields,
    query,
    time_query,
)


def fake_instance(factor=1.5, request="request"):
    d0 = max(0.1, 2 * 0.05)
    return {
        "schema_version": 1,
        "n": 5,
        "norm": "Linf",
        "planner": "SANDO",
        "source_id": "source",
        "config_id": "config",
        "scene_id": "scene-seed0",
        "episode_id": "episode",
        "request_id": request,
        "factor_id": str(factor),
        "factor": factor,
        "initial_dt": 0.1,
        "dc": 0.05,
        "segment_dt": d0 * factor,
        "planning_start_time": 1.0,
        "observation_time": 0.9,
        "t0": 1.1,
        "start": [0.0, 0.0, 1.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0],
        "goal": [2.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "map_bounds": [-10.0, 10.0, -10.0, 10.0, 0.0, 5.0],
        "outcome": {
            "status": 2,
            "residuals": {
                "valid": True,
                "bounds": 0.0,
                "constraints": 0.0,
                "integrality": 0.0,
                "objective": 0.0,
                "reason": "",
            },
            "objective": 3.5,
        },
    }


class ReconstructableRequestTest(unittest.TestCase):
    def test_time_query_137_matches_cpp_formula(self):
        result = time_query(5, 0.001, 0.01, 1.37)
        self.assertAlmostEqual(result["d0"], 0.02)
        self.assertAlmostEqual(result["segment_dt"], 0.0274)
        self.assertAlmostEqual(result["T"], 0.137)
        self.assertEqual(len(result["layer_end_times"]), 5)
        for index, end in enumerate(result["layer_end_times"]):
            self.assertAlmostEqual(end, (index + 1) * 0.0274)

    def test_from_planning_instance_lists_visible_map_as_missing(self):
        snapshot = from_planning_instance(fake_instance())
        self.assertEqual(snapshot["kind"], "sando_reconstructable_request")
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["goal_frame"], "local_E")
        self.assertIn("visible_map", snapshot["missing_fields"])
        self.assertIn("visible_map", missing_observation_fields(snapshot))

    def test_query_at_original_factor_is_same_factor_reference(self):
        instance = fake_instance()
        snapshot = from_planning_instance(instance)
        record = query(snapshot, instance["factor"], original_instance=instance)
        self.assertEqual(record["classification"], "same_factor_reference")
        self.assertTrue(record["original_segment_dt_matches_formula"])
        self.assertEqual(record["status"], 2)
        self.assertEqual(record["objective"], 3.5)
        self.assertEqual(record["residuals"]["valid"], True)

    def test_query_at_137_is_blocked_when_map_absent(self):
        instance = fake_instance()
        snapshot = from_planning_instance(instance)
        record = query(snapshot, 1.37, original_instance=instance)
        self.assertEqual(record["classification"], "blocked_missing_observation")
        self.assertIn("visible_map", record["missing_fields"])
        self.assertAlmostEqual(record["segment_dt"], time_query(5, 0.1, 0.05, 1.37)["segment_dt"])

    def test_outcome_reconstructable_fills_safety_and_path(self):
        instance = fake_instance()
        instance["outcome"]["reconstructable"] = {
            "v_max": 3.0, "a_max": 5.0, "j_max": 8.0,
            "jerk_smooth_weight": 1.0, "environment_assumption": "dynamic",
            "global_path": [[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]],
            "visible_map": None,
        }
        snapshot = from_planning_instance(instance)
        self.assertEqual(snapshot["safety"]["v_max"], 3.0)
        self.assertEqual(snapshot["safety"]["environment_assumption"], "dynamic")
        self.assertEqual(len(snapshot["corridor_build"]["global_path"]), 2)
        self.assertIn("visible_map", snapshot["missing_fields"])
        self.assertNotIn("v_max", snapshot["missing_fields"])


if __name__ == "__main__":
    unittest.main()
