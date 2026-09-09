#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from report_integer_learning_evaluation import make_report
from run_integer_learning_evaluation import config_matches, config_sha, episode_record, layout_sha, run_matrix, runner_command
import run_integer_learning_evaluation as evaluation


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
    command = runner_command(Path("/repo"), item, Path("/tmp/run"), Path("/tmp/setup.bash"), {"bc": Path("/tmp/bc.json"), "cost": Path("/tmp/cost.json"), "set": Path("/tmp/set.json"), "objective": Path("/tmp/objective.json"), "closed_loop": Path("/tmp/closed.json")})
    assert "--policy" in command and "--method" in command
    assert command[command.index("--metrics") + 1] == "/tmp/run/replan_metrics.jsonl"
    assert all("--policy" in runner_command(Path("/repo"), dict(item, method=method), Path("/tmp/run"), Path("/tmp/setup.bash"), {name: Path(f"/tmp/{name}.json") for name in ("bc", "cost", "set", "objective", "closed_loop")}) for method in ("bc", "cost", "set", "objective", "closed_loop"))
    from run_integer_learning_evaluation import ALIGNED_METHODS, aligned_matrix
    aligned = aligned_matrix([200], ALIGNED_METHODS, shuffle_seed=7)
    assert len(aligned) == 36 and {item["method"] for item in aligned} == set(ALIGNED_METHODS)
    assert aligned == aligned_matrix([200], ALIGNED_METHODS, shuffle_seed=7)
    assert aligned != aligned_matrix([200], ALIGNED_METHODS, shuffle_seed=8)
    for seeds in ([], [200, 200], [199], [True]):
        try:
            aligned_matrix(seeds)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid aligned seeds accepted: {seeds}")
    test_mocked_evaluation_resume_lifecycle()
    print("integer evaluation campaign tests passed")


def test_mocked_evaluation_resume_lifecycle():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); setup = root / "setup.bash"; setup.write_text("setup\n")
        source = root / "source.manifest"; source.write_text("source\n")
        output = root / "evaluation"
        args = type("Args", (), {"output": output, "setup_bash": setup, "protocol": "benchmark_aligned_v1", "methods": ["original"], "seeds": [200], "families": ["unknown_dynamic"], "shuffle_seed": 0, "report_seed": 0, "bc_model": None, "cost_model": None, "closed_loop_model": None, "set_model": None, "objective_model": None, "resume": False})()
        old_lock, old_runtime, old_run = evaluation.lock_manifest, evaluation._runtime_identity, evaluation.subprocess.run
        runtime_value = ["stable"]
        calls = []; crash = [False]
        def fake_lock(path, setup_path, models, shuffle_seed):
            return {"schema_version": 1, "setup_bash": evaluation.file_identity(setup_path), "source_manifest": evaluation.file_identity(source), "models": {}, "shuffle_seed": shuffle_seed, "methods": evaluation.METHODS, "expected_scene_matrix": evaluation.run_matrix(shuffle_seed)}
        def fake_run(command, **kwargs):
            calls.append(command)
            if crash[0]:
                crash[0] = False
                raise KeyboardInterrupt()
            run_dir = Path(command[command.index("--output") + 1]); run_dir.mkdir(parents=True, exist_ok=True)
            scene = command[command.index("--scene-family") + 1] if "--scene-family" in command else "n50-d0-seed200"
            item_seed = int(command[command.index("--seed") + 1]); ratio = float(command[command.index("--dynamic-ratio") + 1])
            (run_dir / "config.json").write_text(json.dumps({"seed": item_seed, "num_obstacles": int(command[command.index("--num-obstacles") + 1]), "dynamic_ratio": ratio, "method": "original", "environment_assumption": "dynamic", "planner": "astar_heat"}))
            (run_dir / "obstacles.json").write_text("{}")
            (run_dir / "source_identity.json").write_text(json.dumps({"integer_learning_source_manifest": {"sha256": evaluation.file_identity(source)["sha256"]}}))
            (run_dir / "result.json").write_text(json.dumps({"success": False, "task_duration_s": None}))
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        evaluation.lock_manifest, evaluation._runtime_identity, evaluation.subprocess.run = fake_lock, lambda args: {"runtime": runtime_value[0]}, fake_run
        try:
            crash_output = root / "crash-evaluation"; args.output = crash_output; crash[0] = True
            try:
                evaluation.run_campaign(args)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("simulated evaluation crash did not propagate")
            args.resume = True; evaluation.run_campaign(args)
            assert list((crash_output / "attempts").iterdir())
            args.output = output; args.resume = False
            evaluation.run_campaign(args)
            first_calls = len(calls); args.resume = True; evaluation.run_campaign(args)
            assert len(calls) == first_calls
            runtime_value[0] = "changed"
            try: evaluation.run_campaign(args)
            except ValueError as error: assert "identity mismatch" in str(error)
            else: raise AssertionError("changed runtime identity was accepted")
            runtime_value[0] = "stable"
            args.resume = False
            next((output / "runs").glob("0001-*-original/config.json")).write_text("corrupt")
            args.resume = True
            try: evaluation.run_campaign(args)
            except ValueError as error: assert "changed" in str(error)
            else: raise AssertionError("corrupted evaluation artifact was accepted")
        finally:
            evaluation.lock_manifest, evaluation._runtime_identity, evaluation.subprocess.run = old_lock, old_runtime, old_run


if __name__ == "__main__":
    main()
