#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from report_integer_learning_evaluation import make_report
from run_integer_learning_evaluation import config_matches, config_sha, episode_record, layout_sha, run_matrix, runner_command


def main():
    matrix = run_matrix(7)
    assert len(matrix) == 900
    assert {item["method"] for item in matrix} == {"original", "previous", "bc", "cost", "closed_loop"}
    assert len({item["scene_id"] for item in matrix}) == 180
    assert matrix == run_matrix(7) and matrix != run_matrix(8)

    item = next(row for row in matrix if row["scene_id"] == "n50-d0-seed200" and row["method"] == "bc")
    result = {"success": True, "goal_time_sec": 12., "goal_sent_wall_unix": 10., "observation_end_wall_unix": 20., "ground_truth": {"collision": {"collision": False}}, "tracking_error": {"rmse_m": .02}}
    metrics = [{"schema_version": 1, "request_id": "r", "wall_unix_time": 9., "total_ms": 100., "planning_attempted": True},
               {"schema_version": 1, "request_id": "r", "wall_unix_time": 11., "total_ms": 20., "planning_attempted": True, "success": True, "append_success": True, "selected_factor_index": 0, "parallel_ms": 7., "cancel_drain_ms": 8., "factors": [
                   {"decomp_ms": 5., "policy": {"ranking_ms": 1., "qp_ms": 2., "fallback_ms": 3., "model_prepare_ms": 4., "fallback_used": True, "attempts": [{"kind": "qp", "success": True, "validation_ms": .5, "residuals": {"valid": True}}]}},
                   {"decomp_ms": 6., "policy": {"ranking_ms": 10., "qp_ms": 20., "fallback_ms": 30., "model_prepare_ms": 40., "fallback_used": False, "attempts": [{"kind": "qp", "success": True, "validation_ms": 1.5, "residuals": {"valid": False}}]}}
               ]}]
    record = episode_record(item, result, metrics)
    assert record["planning_latency_ms"] == [20.]
    assert record["constraint_checks"] == {"accepted": 1, "checked": 1, "violations": 0}
    components = record["planning_components_ms"]
    assert {key: components[key] for key in ("ranking_ms", "qp_ms", "fallback_ms", "model_prepare_ms")} == {"ranking_ms": 11., "qp_ms": 22., "fallback_ms": 33., "model_prepare_ms": 44.}
    assert {key: components[key] for key in ("parallel_ms", "cancel_drain_ms", "validation_ms", "decomp_ms")} == {"parallel_ms": 7., "cancel_drain_ms": 8., "validation_ms": 2., "decomp_ms": 11.}
    assert record["component_times_non_additive"] is True
    assert record["planning_request_count"] == 1 and record["factor_request_count"] == 2
    assert record["fallback_request_count"] == 1 and record["accepted_fallback_count"] == 1
    assert record["fallback_count"] == 1 and record["planning_failure_count"] == 0
    assert record["task_duration_s"] == 12.
    assert record["collision"] is False and record["tracking_error"] == .02
    missing = dict(metrics[1]); missing["factors"] = [{"policy": {"attempts": [{"success": True}]}}]
    assert episode_record(item, result, [missing])["constraint_checks"] == {"accepted": 1, "checked": 0, "violations": 0}
    empty = episode_record(item, {"success": False}, [])
    assert empty["planning_latency_ms"] == []
    assert make_report([empty])["environments"]["static"]["methods"]["bc"]["latency_ms"]["frame_count"] == 0
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        (run_dir / "obstacles.json").write_text('{"boxes": []}\n', encoding="utf-8")
        config = {"seed": item["seed"], "num_obstacles": item["num_obstacles"], "dynamic_ratio": item["dynamic_ratio"], "method": item["method"], "environment_assumption": item["environment"], "planner": "astar_heat", "policy_identity": {"sha256": "model-sha"}}
        (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        assert layout_sha(run_dir) == layout_sha(run_dir) and config_sha(run_dir)
        assert config_matches(run_dir, item, "model-sha")
        config["seed"] += 1
        (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        assert not config_matches(run_dir, item, "model-sha")
    command = runner_command(Path("/repo"), item, Path("/tmp/run"), Path("/tmp/setup.bash"), {"bc": Path("/tmp/bc.json"), "cost": Path("/tmp/cost.json"), "closed_loop": Path("/tmp/closed.json")})
    assert "--policy" in command and "--method" in command
    assert command[command.index("--metrics") + 1] == "/tmp/run/replan_metrics.jsonl"
    print("integer evaluation campaign tests passed")


if __name__ == "__main__":
    main()
