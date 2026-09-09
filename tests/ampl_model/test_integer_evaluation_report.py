#!/usr/bin/env python3
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from report_integer_learning_evaluation import make_report, paired_bootstrap, summarize_environment
from integer_scene_protocol import launch_spec, scene_id as protocol_scene_id


def record(scene, method, environment="static", success=True, latency=(10., 20.), duration=10., seed=200, num_obstacles=50):
    ratio = 0.0 if environment == "static" else .65
    scene = f"n{num_obstacles}-d{ratio:g}-seed{seed}"
    return {"scene_id": scene, "method": method, "environment": environment, "split": "test", "seed": seed,
            "num_obstacles": num_obstacles, "dynamic_ratio": ratio, "planning_latency_ms": list(latency), "success": success, "task_duration_s": duration,
            "collision": False, "tracking_error": .1, "constraint_checks": {"accepted": 1, "checked": 1, "violations": 0}}


def main():
    records = []
    for environment in ("static", "dynamic"):
        for scene, base_latency, seed in (("seed1", (10., 20.), 200), ("seed2", (30., 40.), 201)):
            records.append(record(scene, "original", environment, True, base_latency, 10., seed=seed))
            records.append(record(scene, "bc", environment, True, tuple(x * .5 for x in base_latency), 10.5, seed=seed))
    report = make_report(records, seed=7)
    assert report["environments"]["static"]["n_scenes_by_method"]["original"] == 2
    assert report["environments"]["dynamic"]["n_scenes_by_method"]["bc"] == 2
    assert "50" in report["environments"]["static"]["by_num_obstacles"]
    bc = report["environments"]["static"]["methods"]["bc"]
    assert bc["n_common_scenes"] == 2 and bc["gate_vs_original"]["status"] == "pass"
    assert bc["paired_to_original"]["latency_p50_ratio"]["n"] == 2
    assert "p99" in bc["latency_ms"] and bc["latency_ms"]["frame_count"] == 4
    assert bc["paired_to_original"]["common_success_flight_time_ratio"]["estimate"] == 1.05

    reordered = list(reversed(records))
    assert make_report(reordered, seed=7) == report
    incomplete = [item for item in records if not (item["method"] == "bc" and item["scene_id"] == "n50-d0-seed201")]
    assert summarize_environment(incomplete, "static")["methods"]["bc"]["gate_vs_original"]["status"] == "insufficient"

    failures = [record("seed1", "original", success=False, duration=None), record("seed1", "bc", success=False, duration=None)]
    for item in failures:
        item.pop("collision"); item.pop("tracking_error")
        item["constraint_checks"] = {"accepted": 0, "checked": 0, "violations": 0}
    failure_report = make_report(failures)
    failure_bc = failure_report["environments"]["static"]["methods"]["bc"]
    assert failure_bc["flight_time_s_failure_capped"]["median"] == 100.
    assert failure_bc["gate_vs_original"]["status"] == "insufficient"
    assert failure_bc["evidence"]["collision"]["available"] is False

    no_original = make_report([record("seed1", "bc", seed=200)])
    assert no_original["environments"]["static"]["methods"]["bc"]["gate_vs_original"]["status"] == "insufficient"
    violated = copy.deepcopy(records)
    for item in violated:
        if item["method"] == "bc":
            item["constraint_checks"]["violations"] = 1
    assert make_report(violated)["environments"]["static"]["methods"]["bc"]["gate_vs_original"]["status"] == "fail"
    collision = copy.deepcopy(records)
    for item in collision:
        if item["method"] == "bc":
            item["collision"] = True
    collision_gate = make_report(collision)["environments"]["static"]["methods"]["bc"]
    assert collision_gate["gate_vs_original"]["status"] == "pass"
    assert collision_gate["evidence"]["collision"]["rate"] == 1.0
    missing_constraints = copy.deepcopy(records)
    for item in missing_constraints:
        item.pop("constraint_checks")
    assert make_report(missing_constraints)["environments"]["static"]["methods"]["bc"]["gate_vs_original"]["status"] == "insufficient"

    samples = paired_bootstrap([1., 3.], [0., 0.], seed=3, samples=100)
    assert samples["n"] == 2  # the two scenes are the only bootstrap units, not latency frames.
    aligned = []
    for family in ("static_forest", "unknown_dynamic", "known_dynamic"):
        ratio = 0.0 if family == "static_forest" else 0.65
        spec = launch_spec(family, 50, ratio)
        aligned.append({"scene_id": protocol_scene_id(family, 200, 50, ratio, "benchmark_aligned_v1"),
                        "method": "original", "environment": spec["environment_assumption"],
                        "split": "test", "seed": 200, "num_obstacles": 50,
                        "dynamic_ratio": spec["dynamic_ratio"], "family": family,
                        "protocol_id": "benchmark_aligned_v1", "difficulty": spec["difficulty"],
                        "information_boundary": spec["information_boundary"],
                        "planning_latency_ms": [1.], "success": True, "task_duration_s": 1.})
    aligned_report = make_report(aligned)
    assert "known_dynamic" not in aligned_report["environments"]["dynamic"]["n_scenes_by_method"]
    assert aligned_report["families"]["known_dynamic"]["n_scenes_by_method"]["original"] == 1
    assert aligned_report["families"]["static_forest"]["n_scenes_by_method"]["original"] == 1
    print("integer evaluation report tests passed")


if __name__ == "__main__":
    main()
