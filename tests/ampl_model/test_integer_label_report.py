#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from report_integer_learning_labels import load_labels, make_report, validate_label


def attempt(wall, *, status=2):
    return {"status": status, "wall_time": wall, "backend_time": wall / 2, "objective": -1.0,
            "residuals": {"valid": True, "bounds": 0.0, "constraints": 0.0, "integrality": 0.0, "objective": 0.0, "reason": ""}, "error": ""}


def label(scene, classifications, wall, reason=None, retries=0):
    candidates = []
    for index, classification in enumerate(classifications):
        attempts = [attempt(wall / (index + 1))]
        if index == 0 and retries:
            attempts.append(attempt(wall / (index + 2), status=3))
        candidates.append({"assignment": [index], "classification": classification,
                           "model_conversion_time": 0.01, "raw_objective": -1.0 if classification == "feasible" else None,
                           "cost": 0.0 if classification == "feasible" else None, "attempts": attempts})
    counts = {name: classifications.count(name) for name in ("feasible", "infeasible", "unknown")}
    complete = classifications.count("feasible") > 0 and counts["unknown"] == 0 and reason is None
    return {"schema_version": 1,
            "instance": {"scene_id": scene, "episode_id": "ep", "request_id": "req", "factor_id": "factor", "n": 1,
                         "valid_mask": [[True, True]] if candidates else [[]]},
            "total_valid_assignments": len(candidates),
            "costs_complete": complete,
            "failurestats": {"unknown": counts["unknown"], "proven_infeasible": counts["infeasible"], "all_infeasible": bool(candidates) and counts["infeasible"] == len(candidates)},
            "timing": {"covered": len(candidates) if complete else 0, "excluded": 0 if complete else len(candidates), "wall_seconds": wall, "solve_and_residual_wall_seconds": wall * .9,
                       "backend_seconds": wall * .4, "model_conversion_seconds": .01, "attempt_count": len(candidates) + bool(retries), "retries": int(bool(retries))},
            "candidates": candidates,
            **({"excluded_reason": reason} if reason is not None else {})}


def main():
    complete = label("scene-complete", ["feasible", "infeasible"], 1.0, retries=1)
    all_infeasible = label("scene-all-infeasible", ["infeasible", "infeasible"], 2.0, reason="all_infeasible")
    unknown = label("scene-unknown", ["feasible", "unknown"], 3.0, reason="unknown_or_infeasible_results")
    unknown["candidates"][1]["attempts"][0]["backend_time"] = -.2
    unknown["timing"]["backend_seconds"] = -.2
    empty = label("scene-empty", [], .5, reason="no_valid_assignments")
    rows = [complete, all_infeasible, unknown, empty]
    for number, row in enumerate(rows, 1):
        assert validate_label(row, number) is row
    report = make_report(rows, expected_instances=5)
    assert report["actual_instances"] == 4 and report["expected_instances"] == 5
    assert report["incomplete"] is True
    assert report["complete_instances"] == 1
    assert report["all_infeasible_instances"] == 1
    assert report["unknown_instances"] == 1
    assert report["usable_instances"] == 1 and report["usable_fraction"] == .25
    assert report["excluded_instances"] == 3
    assert report["candidate_counts"] == {"total": 6, "feasible": 2, "infeasible": 3, "proven_infeasible": 3, "unknown": 1}
    assert report["candidate_outcomes"] == report["candidate_counts"] and report["candidate_retries"] == 1
    assert report["exclusion_reasons"] == {"all_infeasible": 1, "no_valid_assignments": 1, "unknown_or_infeasible_results": 1}
    assert report["retries"] == {"attempts": 7, "candidate_retries": 1, "instances_with_retries": 1}
    timing = report["wall_labeling_seconds"]
    assert timing["total"] == 6.5 and timing["p50"] == 1.5 and timing["p95"] == 2.85 and timing["p99"] == 2.97
    assert report["invalid_backend_timing_attempts"] == 1
    assert report["recorded_timing_seconds"]["backend_total"] is None
    assert abs(report["recorded_timing_seconds"]["backend_total_raw"] - 1.2) < 1e-12

    # A complete all-infeasible enumeration is a legitimate label result and
    # is reported as excluded from the reusable cost dataset, not rejected.
    assert make_report([all_infeasible], expected_instances=1)["incomplete"] is False

    malformed = json.loads(json.dumps(complete))
    malformed["total_valid_assignments"] = 99
    try:
        validate_label(malformed, 1)
    except ValueError as error:
        assert "disagrees" in str(error)
    else:
        raise AssertionError("malformed label was accepted")
    signed = json.loads(json.dumps(complete))
    signed["candidates"][0]["raw_objective"] = -3.0
    signed["candidates"][0]["attempts"][0]["objective"] = -4.0
    assert validate_label(signed, 1) is signed
    contradiction = json.loads(json.dumps(unknown))
    contradiction["costs_complete"] = True
    try:
        validate_label(contradiction, 1)
    except ValueError as error:
        assert "costs_complete" in str(error)
    else:
        raise AssertionError("contradictory completeness was accepted")
    duplicate = json.loads(json.dumps(complete))
    duplicate["candidates"][1]["assignment"] = duplicate["candidates"][0]["assignment"]
    try:
        validate_label(duplicate, 1)
    except ValueError as error:
        assert "duplicated" in str(error) or "cover" in str(error)
    else:
        raise AssertionError("duplicate assignment was accepted")
    partial = json.loads(json.dumps(complete))
    partial["candidates"][0]["assignment"] = []
    try:
        validate_label(partial, 1)
    except ValueError as error:
        assert "assignment" in str(error)
    else:
        raise AssertionError("partial assignment was accepted")
    boolean_schema = json.loads(json.dumps(complete))
    boolean_schema["schema_version"] = True
    try:
        validate_label(boolean_schema, 1)
    except ValueError as error:
        assert "schema_version" in str(error)
    else:
        raise AssertionError("boolean schema version was accepted")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as duplicate_file:
        duplicate_file.write(json.dumps(complete) + "\n" + json.dumps(complete) + "\n")
        duplicate_path = Path(duplicate_file.name)
    try:
        try:
            load_labels([duplicate_path])
        except ValueError as error:
            assert "duplicates" in str(error)
        else:
            raise AssertionError("duplicate label identity was accepted")
    finally:
        duplicate_path.unlink()

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        input_path = root / "labels.jsonl"
        output_path = root / "report.json"
        input_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        command = [sys.executable, str(Path(__file__).parents[2] / "scripts/report_integer_learning_labels.py"), "--input", str(input_path), "--output", str(output_path), "--expected-instances", "4"]
        assert subprocess.run(command, check=False).returncode == 0
        assert json.loads(output_path.read_text())["actual_instances"] == 4
        assert subprocess.run(command, check=False).returncode == 2
        bad_input = root / "bad.jsonl"
        bad_input.write_text("{}\n", encoding="utf-8")
        bad_output = root / "bad-report.json"
        assert subprocess.run([sys.executable, str(Path(__file__).parents[2] / "scripts/report_integer_learning_labels.py"), "--input", str(bad_input), "--output", str(bad_output)], check=False).returncode == 2
        assert not bad_output.exists()
    print("integer label report tests passed")


if __name__ == "__main__":
    main()
