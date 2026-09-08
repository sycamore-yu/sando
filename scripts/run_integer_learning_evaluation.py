#!/usr/bin/env python3
"""Run the locked five-method integer-learning test campaign serially.

The campaign is 30 test seeds (200--229), each at 50/100/200 obstacles and
static/0.65 dynamic ratio, with one episode for each of original, previous,
bc, cost, and closed_loop.  Every output directory is created exclusively;
the manifest and deterministic shuffled run matrix are written before the
first subprocess starts.  This module does not bootstrap or interpret frames:
it converts per-replan metrics into one episode record for
``report_integer_learning_evaluation``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from report_integer_learning_evaluation import make_report

METHODS = ("original", "previous", "bc", "cost", "closed_loop")
SEEDS = tuple(range(200, 230))
COUNTS = (50, 100, 200)
RATIOS = (0.0, 0.65)


def file_identity(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "size": path.stat().st_size}


def scene_id(seed: int, count: int, ratio: float) -> str:
    return f"n{count}-d{ratio:g}-seed{seed}"


def run_matrix(shuffle_seed: int = 0) -> list[dict[str, Any]]:
    matrix = []
    for seed in SEEDS:
        for count in COUNTS:
            for ratio in RATIOS:
                methods = list(METHODS)
                random.Random(shuffle_seed + seed * 1000 + count + int(ratio * 100)).shuffle(methods)
                for method in methods:
                    matrix.append({"scene_id": scene_id(seed, count, ratio), "seed": seed, "num_obstacles": count, "dynamic_ratio": ratio, "environment": "static" if ratio == 0.0 else "dynamic", "method": method})
    return matrix


def lock_manifest(output: Path, setup_bash: Path, models: dict[str, Path], shuffle_seed: int = 0) -> dict[str, Any]:
    source_manifest = Path("/opt/sando-integer-source.json")
    frozen = output / "frozen_models"; frozen.mkdir()
    frozen_models = {}
    for method, path in models.items():
        destination = frozen / f"{method}.json"
        shutil.copy2(path, destination)
        frozen_models[method] = file_identity(destination)
    manifest = {"schema_version": 1, "setup_bash": file_identity(setup_bash), "source_manifest": file_identity(source_manifest), "models": frozen_models, "shuffle_seed": shuffle_seed, "methods": METHODS, "expected_scene_matrix": run_matrix(shuffle_seed)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def runner_command(repo: Path, item: dict[str, Any], output: Path, setup_bash: Path, models: dict[str, Path]) -> list[str]:
    command = [sys.executable, str(repo / "scripts/integer_learning_baseline_sim.py"), "--output", str(output), "--setup-bash", str(setup_bash), "--method", item["method"], "--seed", str(item["seed"]), "--num-obstacles", str(item["num_obstacles"]), "--dynamic-ratio", str(item["dynamic_ratio"]), "--metrics", str(output / "replan_metrics.jsonl")]
    if item["method"] in models:
        command.extend(("--policy", str(models[item["method"]])))
    return command


def _constraint_metrics(metrics: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, int]:
    accepted = checked = violations = 0
    for metric in metrics:
        if not metric.get("append_success", False):
            continue
        accepted += 1
        selected = metric.get("selected_factor_index")
        factors = metric.get("factors", [])
        factor = factors[selected] if isinstance(selected, int) and 0 <= selected < len(factors) else None
        attempts = factor.get("policy", {}).get("attempts", []) if isinstance(factor, dict) else []
        successful = [attempt for attempt in attempts if attempt.get("success")]
        attempt = successful[0] if successful else None
        residuals = attempt.get("residuals") if isinstance(attempt, dict) else None
        if isinstance(residuals, dict):
            checked += 1
            if not residuals.get("valid", False):
                violations += 1
        else:
            pass
    return {"accepted": accepted, "checked": checked, "violations": violations}


def _in_observation_window(metric: dict[str, Any], result: dict[str, Any]) -> bool:
    timestamp = metric.get("wall_unix_time")
    start = result.get("goal_sent_wall_unix")
    end = result.get("observation_end_wall_unix")
    return isinstance(timestamp, (int, float)) and isinstance(start, (int, float)) and isinstance(end, (int, float)) and start <= timestamp <= end


def layout_sha(run_dir: Path) -> str | None:
    obstacle_file = run_dir / "obstacles.json"
    if not obstacle_file.is_file():
        return None
    return file_identity(obstacle_file)["sha256"]


def config_sha(run_dir: Path) -> str | None:
    """Return the hash of the per-run configuration captured by the simulator."""
    config_file = run_dir / "config.json"
    if not config_file.is_file():
        return None
    return file_identity(config_file)["sha256"]


def config_matches(run_dir: Path, item: dict[str, Any], model_sha: str | None) -> bool:
    """Check that a run's recorded configuration describes its matrix item."""
    config_file = run_dir / "config.json"
    if not config_file.is_file():
        return False
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = {
        "seed": item["seed"],
        "num_obstacles": item["num_obstacles"],
        "dynamic_ratio": item["dynamic_ratio"],
        "method": item["method"],
        "environment_assumption": item["environment"],
        "planner": "astar_heat",
    }
    if any(config.get(key) != value for key, value in expected.items()):
        return False
    policy = config.get("policy_identity")
    recorded_sha = policy.get("sha256") if isinstance(policy, dict) else None
    return recorded_sha == model_sha


def episode_record(item: dict[str, Any], result: dict[str, Any] | None, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    result = result or {}
    selected_metrics = [metric for metric in metrics if _in_observation_window(metric, result) and metric.get("planning_attempted", False)]
    component_keys = ("ranking_ms", "qp_ms", "fallback_ms", "model_prepare_ms")
    component_totals = {key: 0.0 for key in (*component_keys, "parallel_ms", "cancel_drain_ms", "validation_ms", "decomp_ms")}
    fallback_count = planning_failures = fallback_requests = factor_requests = accepted_fallbacks = 0
    for metric in selected_metrics:
        request_fallback = False
        for key in ("parallel_ms", "cancel_drain_ms"):
            component_totals[key] += float(metric.get(key, 0.0))
        for factor in metric.get("factors", []):
            policy = factor.get("policy", {}) if isinstance(factor, dict) else {}
            for key in component_keys: component_totals[key] += float(policy.get(key, 0.0)) if isinstance(policy.get(key, 0.0), (int, float)) else 0.0
            factor_requests += bool(policy.get("attempts"))
            fallback_count += bool(policy.get("fallback_used", False))
            request_fallback |= bool(policy.get("fallback_used", False))
            component_totals["decomp_ms"] += float(factor.get("decomp_ms", 0.0))
            component_totals["validation_ms"] += sum(float(attempt.get("validation_ms", 0.0)) for attempt in policy.get("attempts", []))
        fallback_requests += request_fallback
        selected = metric.get("selected_factor_index")
        factors = metric.get("factors", [])
        if metric.get("append_success") and isinstance(selected, int) and 0 <= selected < len(factors):
            accepted_fallbacks += bool(factors[selected].get("policy", {}).get("fallback_used", False))
        planning_failures += not bool(metric.get("success", False))
    record = {"scene_id": item["scene_id"], "method": item["method"], "environment": item["environment"], "split": "test", "seed": item["seed"], "num_obstacles": item["num_obstacles"], "dynamic_ratio": item["dynamic_ratio"], "planning_latency_ms": [float(metric["total_ms"]) for metric in selected_metrics if isinstance(metric.get("total_ms"), (int, float))], "success": bool(result.get("success", False)), "constraint_checks": _constraint_metrics(selected_metrics, result), "light_metrics": selected_metrics, "planning_components_ms": component_totals, "fallback_count": fallback_count, "planning_failure_count": planning_failures,
              "planning_request_count": len(selected_metrics),
              "fallback_request_count": fallback_requests,
              "accepted_fallback_count": accepted_fallbacks,
              "component_times_non_additive": True,
              "factor_request_count": factor_requests,
              "request_fallback_rate": fallback_requests / len(selected_metrics) if selected_metrics else None,
              "factor_fallback_rate": fallback_count / factor_requests if factor_requests else None,
              "planning_failure_rate": planning_failures / len(selected_metrics) if selected_metrics else None}
    duration = result.get("task_duration_s", result.get("goal_time_sec", result.get("elapsed_sec")))
    if duration is not None:
        record["task_duration_s"] = duration
    collision = result.get("ground_truth", {}).get("collision", {})
    if isinstance(collision, dict) and isinstance(collision.get("collision"), bool):
        record["collision"] = collision["collision"]
    tracking = result.get("tracking_error")
    if isinstance(tracking, dict) and tracking.get("rmse_m") is not None:
        record["tracking_error"] = tracking["rmse_m"]
    return record


def run_campaign(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.mkdir(parents=False, exist_ok=False)
    (output / "runs").mkdir()
    models = {"bc": Path(args.bc_model), "cost": Path(args.cost_model), "closed_loop": Path(args.closed_loop_model)}
    manifest = lock_manifest(output, Path(args.setup_bash), models, args.shuffle_seed)
    models = {method: Path(identity["path"]) for method, identity in manifest["models"].items()}
    repo = Path(__file__).resolve().parents[1]
    episodes: list[dict[str, Any]] = []
    with (output / "progress.jsonl").open("x", encoding="utf-8") as progress:
        for index, item in enumerate(manifest["expected_scene_matrix"], 1):
            run_dir = output / "runs" / f"{index:04d}-{item['scene_id']}-{item['method']}"
            run_dir.mkdir()
            metrics_path = run_dir / "replan_metrics.jsonl"
            started = time.time()
            command = runner_command(repo, item, run_dir, Path(args.setup_bash), models)
            completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)
            result_path = run_dir / "result.json"
            result = json.loads(result_path.read_text()) if result_path.is_file() else None
            identity_path = run_dir / "source_identity.json"
            source_identity = json.loads(identity_path.read_text()) if identity_path.is_file() else None
            metrics = []
            if metrics_path.is_file():
                with metrics_path.open() as stream:
                    metrics = [json.loads(line) for line in stream if line.strip()]
            episode = episode_record(item, result, metrics)
            episode["source_layout_sha"] = layout_sha(run_dir)
            episode["config_sha"] = config_sha(run_dir)
            episode["source_manifest_sha"] = source_identity.get("integer_learning_source_manifest", {}).get("sha256") if isinstance(source_identity, dict) else None
            episode["model_sha"] = result.get("policy_identity", {}).get("sha256") if isinstance(result, dict) and isinstance(result.get("policy_identity"), dict) else None
            episode["config_valid"] = config_matches(run_dir, item, episode["model_sha"])
            episode["instrumentation_error"] = bool(result.get("instrumentation_error", False)) if isinstance(result, dict) else True
            episode["run"] = {"index": index, "returncode": completed.returncode, "wall_seconds": time.time() - started, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]}
            episodes.append(episode)
            progress.write(json.dumps({"index": index, "total": len(manifest["expected_scene_matrix"]), "scene_id": item["scene_id"], "method": item["method"], "returncode": completed.returncode}) + "\n")
            progress.flush()
    report = make_report(episodes, args.report_seed)
    report["campaign"] = {"manifest": "manifest.json", "expected_runs": len(manifest["expected_scene_matrix"]), "completed_runs": len(episodes), "usable_for_report": sum(bool(episode["planning_latency_ms"]) for episode in episodes), "excluded_missing_metrics": sum(not bool(episode["planning_latency_ms"]) for episode in episodes)}
    layouts = {}
    for episode in episodes:
        layouts.setdefault(episode["scene_id"], set()).add(episode.get("source_layout_sha"))
    report["campaign"]["source_layout_mismatches"] = {scene: sorted(value, key=str) for scene, value in layouts.items() if len(value) != 1 or None in value}
    report["campaign"]["source_manifest_mismatches"] = sorted({episode["scene_id"] for episode in episodes if episode.get("source_manifest_sha") != manifest["source_manifest"]["sha256"]})
    report["campaign"]["config_mismatches"] = sorted({episode["scene_id"] + ":" + episode["method"] for episode in episodes if not episode.get("config_valid", False)})
    expected_model_sha = {method: manifest["models"][method]["sha256"] for method in ("bc", "cost", "closed_loop")}
    report["campaign"]["model_mismatches"] = sorted({episode["scene_id"] + ":" + episode["method"] for episode in episodes if episode["method"] in expected_model_sha and episode.get("model_sha") != expected_model_sha[episode["method"]]})
    report["campaign"]["identity_valid"] = not any((report["campaign"][key] for key in ("source_layout_mismatches", "source_manifest_mismatches", "config_mismatches", "model_mismatches")))
    report["campaign"]["instrumentation_errors"] = sorted({episode["scene_id"] + ":" + episode["method"] for episode in episodes if episode.get("instrumentation_error", False)})
    report["campaign"]["data_valid"] = report["campaign"]["identity_valid"] and not report["campaign"]["instrumentation_errors"]
    if not report["campaign"]["data_valid"]:
        reason = "instrumentation_error" if report["campaign"]["instrumentation_errors"] else "source_or_model_identity_mismatch"
        for environment in report.get("environments", {}).values():
            for method in environment.get("methods", {}).values():
                if "gate_vs_original" in method:
                    method["gate_vs_original"] = {"status": "insufficient", "checks": {}, "reason": reason}
            for count in environment.get("by_num_obstacles", {}).values():
                for method in count.get("methods", {}).values():
                    if "gate_vs_original" in method:
                        method["gate_vs_original"] = {"status": "insufficient", "checks": {}, "reason": reason}
    report["campaign"]["component_totals_ms"] = {key: sum(episode["planning_components_ms"][key] for episode in episodes) for key in ("ranking_ms", "qp_ms", "fallback_ms", "model_prepare_ms")}
    report["campaign"]["fallback_count"] = sum(episode["fallback_count"] for episode in episodes)
    report["campaign"]["planning_failure_count"] = sum(episode["planning_failure_count"] for episode in episodes)
    report["episodes"] = episodes
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--setup-bash", required=True)
    parser.add_argument("--bc-model", "--bc-policy", dest="bc_model", required=True)
    parser.add_argument("--cost-model", "--cost-policy", dest="cost_model", required=True)
    parser.add_argument("--closed-loop-model", "--closed-loop-policy", dest="closed_loop_model", required=True)
    parser.add_argument("--shuffle-seed", type=int, default=0)
    parser.add_argument("--report-seed", type=int, default=0)
    return run_campaign(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
