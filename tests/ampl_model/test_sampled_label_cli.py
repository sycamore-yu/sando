#!/usr/bin/env python3
"""Standalone integration checks for sampled label_planning_instances."""
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[2]
LOCAL_SNAPSHOT = ROOT / "docker/dev-workspace/results/learning-stages-v2/snapshot/train/seed18/runs/static_forest-easy-seed18/instances.jsonl"
BIN = Path(os.environ.get("SANDO_LABEL_PLANNING_INSTANCES_BIN", "/root/sando_ws/build-dev/sando/label_planning_instances"))


def official_instance():
    path = Path(os.environ.get("SANDO_OFFICIAL_SNAPSHOT", str(LOCAL_SNAPSHOT)))
    return json.loads(path.read_text().splitlines()[0])


def run_cli(instance_rows, assignment_rows):
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        input_path, assignments_path, output_path = (directory / name for name in ("input.jsonl", "assignments.jsonl", "output.jsonl"))
        input_path.write_text("".join(json.dumps(row) + "\n" for row in instance_rows))
        assignments_path.write_text("".join(json.dumps(row) + "\n" for row in assignment_rows))
        result = subprocess.run([str(BIN), "--input", str(input_path), "--output", str(output_path), "--assignments", str(assignments_path)], text=True, capture_output=True)
        return result, output_path.read_text() if output_path.exists() else ""


def identity(instance):
    return {key: instance[key] for key in ("scene_id", "episode_id", "request_id", "factor_id", "source_id", "config_id")}


def test_sampled_solve_preserves_identity_and_is_accepted():
    instance = official_instance()
    assert len(instance["coefficients"]) == 3
    assert all(len(axis) == 20 for axis in instance["coefficients"])
    assert all(math.isfinite(float(expression["constant"])) for axis in instance["coefficients"] for expression in axis)
    expected_dt = max(float(instance["initial_dt"]), 2.0 * float(instance["dc"])) * float(instance["factor"])
    assert math.isclose(float(instance["segment_dt"]), expected_dt, rel_tol=2e-6, abs_tol=2e-6)
    result, text = run_cli([instance], [{"identity": identity(instance), "assignment": [0, 0, 0, 0, 0]}])
    assert result.returncode == 0, result.stderr
    row = json.loads(text)
    assert row["record_purpose"] == "sampled_candidate"
    assert row["instance"] == instance
    assert row["accepted"] is True
    assert row["candidates"][0]["assignment"] == [0, 0, 0, 0, 0]
    assert row["candidates"][0]["classification"] == "feasible"


def test_assignment_identity_mismatch_is_rejected():
    instance = official_instance()
    bad = identity(instance)
    bad["request_id"] = "wrong"
    result, _ = run_cli([instance], [{"identity": bad, "assignment": [0, 0, 0, 0, 0]}])
    assert result.returncode == 2
    assert "identity does not match" in result.stderr


def test_bad_assignment_is_rejected():
    instance = official_instance()
    result, _ = run_cli([instance], [{"identity": identity(instance), "assignment": [0, 0, 0, 0, 9]}])
    assert result.returncode == 2
    assert "assignment" in result.stderr


def test_missing_identity_and_repeated_rows_remain_aligned():
    instance = official_instance()
    result, text = run_cli([instance, instance], [{"identity": identity(instance), "assignment": [0, 0, 0, 0, 0]}, {"identity": identity(instance), "assignment": [0, 0, 0, 0, 0]}])
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in text.splitlines() if line]
    assert len(rows) == 2
    assert all(row["instance"] == instance for row in rows)


def test_missing_identity_is_rejected():
    instance = official_instance()
    result, _ = run_cli([instance], [{"assignment": [0, 0, 0, 0, 0]}])
    assert result.returncode == 2
    assert "identity" in result.stderr


def test_extra_assignment_record_is_rejected():
    instance = official_instance()
    result, _ = run_cli([instance], [{"identity": identity(instance), "assignment": [0, 0, 0, 0, 0]}, {"identity": identity(instance), "assignment": [0, 0, 0, 0, 0]}])
    assert result.returncode == 2
    assert "more records" in result.stderr


def test_noninteger_assignment_is_rejected():
    instance = official_instance()
    result, _ = run_cli([instance], [{"identity": identity(instance), "assignment": [0, 0, 0, 0, True]}])
    assert result.returncode == 2
    assert "assignment" in result.stderr


def main():
    if not BIN.is_file():
        raise SystemExit(f"missing integration binary: {BIN}")
    for test in (test_sampled_solve_preserves_identity_and_is_accepted, test_assignment_identity_mismatch_is_rejected, test_bad_assignment_is_rejected, test_missing_identity_and_repeated_rows_remain_aligned):
        test()
    print("sampled label CLI tests passed")


if __name__ == "__main__":
    main()
