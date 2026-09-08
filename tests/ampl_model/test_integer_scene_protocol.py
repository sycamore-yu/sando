#!/usr/bin/env python3
"""Host-only checks for capture scene families and start sampling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from integer_scene_protocol import (
    DEFAULT_ALIGNED_FAMILIES,
    GOAL,
    NOMINAL_START,
    aabb_clear,
    aligned_scene_configs,
    launch_spec,
    randomization_for_split,
    resolve_start,
    sample_start,
    scene_id,
)


def test_launch_boundaries():
    unknown = launch_spec("unknown_dynamic", 100)
    assert unknown["env"] == "empty_wo_ground"
    assert unknown["publish_trajs"] is False
    assert unknown["trajs_topic"] == "/trajs_ground_truth"
    assert unknown["information_boundary"] == "pointcloud_only"
    forest = launch_spec("static_forest", 50)
    assert forest["env"] == "easy_forest" and forest["num_obstacles"] == 0
    assert forest["information_boundary"] == "static_world_pointcloud"
    assert forest["same_map_across_seeds"] is True
    known = launch_spec("known_dynamic", 200)
    assert known["mode"] == "rviz-only"
    assert known["publish_trajs"] is True and known["trajs_topic"] == "/trajs"
    assert known["information_boundary"] == "privileged_ground_truth_trajs"


def test_scene_ids():
    assert scene_id("unknown_dynamic", 0, 50, 0.65) == "n50-d0.65-seed0"
    assert scene_id("unknown_dynamic", 0, 50, 0.65, "benchmark_aligned_v1") == (
        "unknown_dynamic-n50-d0.65-seed0"
    )
    assert scene_id("static_forest", 3, 100, 0.0, "benchmark_aligned_v1") == (
        "static_forest-medium-seed3"
    )


def test_start_sampler_is_deterministic_and_boxed():
    first = sample_start("unknown_dynamic-n50-d0.65-seed0", 0)
    again = sample_start("unknown_dynamic-n50-d0.65-seed0", 0)
    other = sample_start("unknown_dynamic-n50-d0.65-seed0", 1)
    assert first == again and first != other
    assert -1.0 <= first[0] <= 3.0
    assert -2.0 <= first[1] <= 2.0
    assert 1.5 <= first[2] <= 2.5
    assert GOAL == (105.0, 0.0, 2.0)


def test_clearance_and_resolve():
    overlapping = [{"x0": 0.0, "y0": 0.0, "z0": 2.0, "size_x": 4.0, "size_y": 4.0, "size_z": 4.0}]
    assert not aabb_clear(NOMINAL_START, overlapping)
    far = [{"x0": 40.0, "y0": 0.0, "z0": 2.0, "size_x": 0.8, "size_y": 0.8, "size_z": 0.8}]
    resolved = resolve_start("unknown_dynamic-n50-d0.65-seed7", "unknown_dynamic", far, "train_box_v1")
    assert resolved["sampler"] == "train_box_v1"
    assert resolved["accepted"] != list(NOMINAL_START)
    assert resolve_start("x", "unknown_dynamic", far, "none")["accepted"] == list(NOMINAL_START)
    forest = resolve_start("static_forest-easy-seed1", "static_forest", overlapping, "train_box_v1")
    assert forest["attempts"] >= 1
    assert randomization_for_split("train_box_v1", "test") == "none"
    assert randomization_for_split("train_box_v1", "validation") == "train_box_v1"


def test_aligned_matrix_excludes_privileged_default():
    rows = aligned_scene_configs("train", [0])
    families = {row["family"] for row in rows}
    assert families == set(DEFAULT_ALIGNED_FAMILIES)
    assert "known_dynamic" not in families
    assert len(rows) == 6
    unknown = [row for row in rows if row["family"] == "unknown_dynamic"]
    assert all(row["dynamic_ratio"] == 0.65 for row in unknown)
    assert all(row["start_randomization"] == "train_box_v1" for row in rows)
    test_rows = aligned_scene_configs("test", [200])
    assert all(row["start_randomization"] == "none" for row in test_rows)
    privileged = aligned_scene_configs("train", [0], families=("known_dynamic",))
    assert privileged[0]["information_boundary"] == "privileged_ground_truth_trajs"


if __name__ == "__main__":
    test_launch_boundaries()
    test_scene_ids()
    test_start_sampler_is_deterministic_and_boxed()
    test_clearance_and_resolve()
    test_aligned_matrix_excludes_privileged_default()
    print("integer scene protocol tests passed")
