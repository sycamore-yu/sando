#!/usr/bin/env python3
"""Standalone checks for reconstructable request snapshots and time queries."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from reconstructable_request import (
    default_reconstruct_binary,
    from_planning_instance,
    missing_observation_fields,
    query,
    reconstruct_query,
    solve_reconstructed,
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

    def test_request_obst_pos_overrides_scene_sidecar(self):
        instance = fake_instance()
        instance["outcome"]["reconstructable"] = {
            "v_max": 3.0, "a_max": 5.0, "j_max": 8.0,
            "jerk_smooth_weight": 1.0, "environment_assumption": "dynamic",
            "global_path": [[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]],
            "obst_pos": [[1.5, 0.0, 1.0]],
            "obst_bbox": [[0.4, 0.4, 1.0]],
            "visible_map": {
                "kind": "classified_points",
                "points": [[0.15, 0.0, 1.0]],
                "classes": [1],
            },
        }
        sidecars = {
            "obstacles": [{"x0": 9.0, "y0": 9.0, "z0": 1.0, "size_x": 1.0, "size_y": 1.0, "size_z": 1.0}],
            "obstacles.json": [{"x0": 9.0, "y0": 9.0, "z0": 1.0, "size_x": 1.0, "size_y": 1.0, "size_z": 1.0}],
        }
        snapshot = from_planning_instance(instance, sidecars)
        self.assertEqual(snapshot["corridor_build"]["obst_pos"], [[1.5, 0.0, 1.0]])
        self.assertEqual(snapshot["corridor_build"]["obst_bbox"], [[0.4, 0.4, 1.0]])
        self.assertNotIn("obst_pos", missing_observation_fields(snapshot))
        self.assertNotIn("visible_map", missing_observation_fields(snapshot))

    def test_observation_file_fills_visible_map_and_unblocks_new_factor(self):
        instance = fake_instance()
        instance["outcome"]["reconstructable"] = {
            "observation_id": "request",
            "v_max": 3.0, "a_max": 5.0, "j_max": 8.0,
            "jerk_smooth_weight": 1.0, "environment_assumption": "dynamic",
            "global_path": [[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]],
            "obst_pos": [[0.8, 0.1, 1.0]],
            "obst_bbox": [[0.3, 0.3, 0.8]],
            "visible_map": {
                "kind": "request_observation",
                "observation_id": "request",
                "sha256": "abc",
                "point_count": 1,
            },
        }
        observation = {
            "kind": "sando_frozen_planning_observation",
            "identity": {"request_id": "request"},
            "obst_pos": [[0.8, 0.1, 1.0]],
            "obst_bbox": [[0.3, 0.3, 0.8]],
            "global_path": [[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]],
            "visible_map": {
                "kind": "classified_points",
                "points": [[0.0, 0.0, 1.0]],
                "classes": [0],
            },
            "safety": {"v_max": 3.0, "a_max": 5.0, "j_max": 8.0, "environment_assumption": "dynamic"},
        }
        snapshot = from_planning_instance(instance, {"observations": {"request": observation}})
        self.assertEqual(snapshot["corridor_build"]["visible_map"]["classes"], [0])
        self.assertEqual(missing_observation_fields(snapshot), [])
        record = query(snapshot, 1.37, original_instance=instance)
        self.assertEqual(record["classification"], "computed_times")
        self.assertEqual(record["missing_fields"], [])

    def test_observation_reference_without_file_stays_blocked(self):
        instance = fake_instance()
        instance["outcome"]["reconstructable"] = {
            "v_max": 3.0, "a_max": 5.0, "j_max": 8.0, "environment_assumption": "dynamic",
            "global_path": [[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]],
            "obst_pos": [[1.0, 0.0, 1.0]],
            "obst_bbox": [[0.2, 0.2, 0.5]],
            "visible_map": {"kind": "request_observation", "observation_id": "request", "sha256": "abc"},
        }
        snapshot = from_planning_instance(instance)
        self.assertIn("visible_map", missing_observation_fields(snapshot))
        self.assertEqual(query(snapshot, 1.37)["classification"], "blocked_missing_observation")

    def test_reconstruct_query_solves_empty_observation(self):
        binary = default_reconstruct_binary()
        if binary is None:
            self.skipTest("reconstruct_planning_request binary is not available")
        observation = {
            "kind": "sando_frozen_planning_observation",
            "schema_version": 1,
            "observation_id": "reconstruct-empty",
            "identity": {
                "source_id": "source",
                "config_id": "config",
                "scene_id": "scene",
                "episode_id": "episode",
                "request_id": "reconstruct-empty",
            },
            "start": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "goal": [3.0, 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "A_time": 0.0,
            "timestamps": {"planning_start_time": 0.0, "observation_time": 0.0, "t0": 0.0},
            "time_inputs": {"n": 5, "initial_dt": 1.0, "dc": 1.0},
            "safety": {
                "v_max": 20, "a_max": 40, "j_max": 100, "jerk_smooth_weight": 1,
                "environment_assumption": "dynamic", "sim_env": "fake_sim",
                "norm": "Linf", "planner": "SANDO",
            },
            "geometry": {
                "res": 0.3, "factor_hgp": 1.0,
                "map_origin": [-2.0, -3.0, -1.0],
                "map_dim": [24, 24, 18],
                "z_min": -1.0, "z_max": 4.0,
                "drone_radius": 0.2,
                "sfc_size": [4.0, 4.0, 4.0],
                "use_shrinked_box": False,
                "shrinked_box_size": 0.0,
                "obst_max_vel": 1.0,
                "obst_position_error": 0.0,
                "inflate_unknown_boundary": True,
                "map_bounds": [-2.0, 5.0, -3.0, 4.0, -1.0, 4.0],
            },
            "global_path": [[0.0, 0.0, 1.0], [3.0, 1.0, 2.0]],
            "obst_pos": [],
            "obst_bbox": [],
            "visible_map": {"kind": "classified_points", "points": [], "classes": []},
        }
        instance = fake_instance(factor=1.0, request="reconstruct-empty")
        instance["initial_dt"] = 1.0
        instance["dc"] = 1.0
        instance["segment_dt"] = 2.0
        instance["outcome"]["reconstructable"] = {
            "v_max": 20, "a_max": 40, "j_max": 100,
            "jerk_smooth_weight": 1.0, "environment_assumption": "dynamic",
            "global_path": observation["global_path"],
            "obst_pos": [],
            "obst_bbox": [],
            "visible_map": observation["visible_map"],
        }
        snapshot = from_planning_instance(instance)
        self.assertEqual(missing_observation_fields(snapshot), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observation.json"
            path.write_text(json.dumps(observation))
            first = reconstruct_query(snapshot, 1.0, observation_path=path, original_instance=instance)
            second = solve_reconstructed(path, 1.0)
            off_grid = reconstruct_query(snapshot, 1.37, observation_path=path)
        self.assertEqual(first["classification"], "optimal")
        self.assertEqual(first["solver_kind"], "miqp")
        self.assertTrue(first["residuals"]["valid"])
        self.assertAlmostEqual(first["objective"], second["objective"], places=8)
        self.assertEqual(off_grid["classification"], "optimal")
        self.assertNotEqual(off_grid["classification"], "computed_times")
        self.assertNotEqual(off_grid["classification"], "blocked_missing_observation")


if __name__ == "__main__":
    unittest.main()
