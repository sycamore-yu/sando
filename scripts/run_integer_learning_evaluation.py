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
from integer_scene_protocol import aligned_scene_configs, scene_id as protocol_scene_id
from capture_integer_learning_campaign import _acquire_lock, _artifact_hashes, _runtime_identity, _write_json

METHODS = ("original", "previous", "bc", "cost", "closed_loop")
ALIGNED_METHODS = ("original", "previous", "bc", "cost", "set", "objective")
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


def aligned_matrix(seeds, methods=ALIGNED_METHODS, families=("unknown_dynamic", "static_forest"), shuffle_seed=0):
    if not seeds or len(set(seeds)) != len(seeds) or any(type(seed) is not int or seed not in SEEDS for seed in seeds):
        raise ValueError("aligned evaluation requires unique locked test seeds 200..229")
    if not methods or len(set(methods)) != len(methods) or any(method not in (*ALIGNED_METHODS, "closed_loop") for method in methods):
        raise ValueError("evaluation requires unique supported methods")
    rows = []
    for config in aligned_scene_configs("test", seeds, COUNTS, families):
        order = list(methods)
        random.Random(f"{shuffle_seed}:{config['scene_id']}").shuffle(order)
        for method in order:
            row = {**config, "method": method, "environment": "static" if config["family"] == "static_forest" else "dynamic"}
            rows.append(row)
    return rows


def lock_manifest(output: Path, setup_bash: Path, models: dict[str, Path], shuffle_seed: int = 0) -> dict[str, Any]:
    source_manifest = Path("/opt/sando-integer-source.json")
    frozen = output / "frozen_models"; frozen.mkdir(exist_ok=True)
    frozen_models = {}
    for method, path in models.items():
        destination = frozen / f"{method}.json"
        if destination.exists():
            if file_identity(destination)["sha256"] != file_identity(path)["sha256"]:
                raise ValueError("interrupted model freeze differs from current input")
        else:
            temporary = destination.with_suffix(".tmp")
            shutil.copy2(path, temporary)
            temporary.replace(destination)
        frozen_models[method] = file_identity(destination)
    manifest = {"schema_version": 1, "setup_bash": file_identity(setup_bash), "source_manifest": file_identity(source_manifest), "models": frozen_models, "shuffle_seed": shuffle_seed, "methods": METHODS, "expected_scene_matrix": run_matrix(shuffle_seed)}
    return manifest


def runner_command(repo: Path, item: dict[str, Any], output: Path, setup_bash: Path, models: dict[str, Path]) -> list[str]:
    command = [sys.executable, str(repo / "scripts/integer_learning_baseline_sim.py"), "--output", str(output), "--setup-bash", str(setup_bash), "--method", item["method"], "--seed", str(item["seed"]), "--num-obstacles", str(item["num_obstacles"]), "--dynamic-ratio", str(item["dynamic_ratio"]), "--metrics", str(output / "replan_metrics.jsonl")]
    if item.get("family"):
        command.extend(("--scene-family", item["family"], "--start-randomization", "none", "--protocol-id", "benchmark_aligned_v1"))
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
    world = run_dir / "static_world.world"
    if world.is_file():
        return file_identity(world)["sha256"]
    obstacle_file = run_dir / "obstacles.json"
    if obstacle_file.is_file():
        return file_identity(obstacle_file)["sha256"]
    config_file = run_dir / "config.json"
    if config_file.is_file():
        try:
            world = json.loads(config_file.read_text()).get("world_file")
            if world and Path(world).is_file():
                return file_identity(world)["sha256"]
        except (OSError, json.JSONDecodeError):
            pass
    return None


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
    if item.get("family"):
        expected.update(scene_family=item["family"], protocol_id=item["protocol_id"], information_boundary=item["information_boundary"])
        if config.get("start", {}).get("sampler") != "none":
            return False
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
    for key in ("family", "difficulty", "information_boundary", "protocol_id"):
        if key in item:
            record[key] = item[key]
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
    args.setup_bash = Path(args.setup_bash)
    if output.exists() and not getattr(args, "resume", False):
        raise ValueError("evaluation output exists; use --resume")
    output.mkdir(parents=True, exist_ok=True)
    with _acquire_lock(output) as lock:
        return _run_campaign(args, lock.fileno())


def _run_campaign(args: argparse.Namespace, lock_fd: int) -> int:
    output = Path(args.output)
    (output / "runs").mkdir(exist_ok=True)
    models = {method: Path(path) for method, path in {
        "bc": getattr(args, "bc_model", None), "cost": getattr(args, "cost_model", None),
        "closed_loop": getattr(args, "closed_loop_model", None), "set": getattr(args, "set_model", None),
        "objective": getattr(args, "objective_model", None)}.items() if path}
    protocol = getattr(args, "protocol", "legacy")
    if protocol == "legacy" and any(getattr(args, name, None) for name in ("methods", "seeds", "families")):
        raise ValueError("evaluation subset options require --protocol benchmark_aligned_v1")
    methods = tuple(getattr(args, "methods", None) or (METHODS if protocol == "legacy" else ALIGNED_METHODS))
    missing_models = set(methods) - {"original", "previous"} - set(models)
    if missing_models:
        raise ValueError(f"missing policy models: {sorted(missing_models)}")
    seeds = getattr(args, "seeds", None) or (SEEDS if protocol == "legacy" else tuple(range(200, 230)))
    if protocol == "benchmark_aligned_v1":
        manifest_matrix = aligned_matrix(seeds, methods, getattr(args, "families", None) or ("unknown_dynamic", "static_forest"), args.shuffle_seed)
    else:
        manifest_matrix = run_matrix(args.shuffle_seed)
    requested = {"protocol": protocol, "methods": methods, "matrix": manifest_matrix,
                 "setup": file_identity(args.setup_bash), "runtime": _runtime_identity(args),
                 "models": {method: file_identity(path) for method, path in models.items()},
                 "scripts": {name: file_identity(Path(__file__).with_name(name))["sha256"] for name in
                             ("run_integer_learning_evaluation.py", "integer_learning_baseline_sim.py",
                              "report_integer_learning_evaluation.py", "integer_scene_protocol.py")}}
    requested = json.loads(json.dumps(requested))
    started_path = output / "started.json"
    if started_path.exists():
        if json.loads(started_path.read_text())["requested_identity"] != requested:
            raise ValueError("interrupted evaluation identity mismatch")
    else:
        _write_json(started_path, {"requested_identity": requested, "created_unix": time.time()})
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("requested_identity") != requested:
            raise ValueError("evaluation resume identity mismatch")
        for identity in manifest["models"].values():
            if file_identity(identity["path"]) != identity:
                raise ValueError("frozen evaluation model changed")
        if file_identity(manifest["source_manifest"]["path"]) != manifest["source_manifest"]:
            raise ValueError("evaluation source manifest changed")
    else:
        manifest = lock_manifest(output, Path(args.setup_bash), models, args.shuffle_seed)
        manifest.update(methods=methods, protocol=protocol, expected_scene_matrix=manifest_matrix,
                        requested_identity=requested)
        _write_json(manifest_path, manifest)
    models = {method: Path(identity["path"]) for method, identity in manifest["models"].items()}
    repo = Path(__file__).resolve().parents[1]
    episodes: list[dict[str, Any]] = []
    with (output / "progress.jsonl").open("a", encoding="utf-8") as progress:
        for index, item in enumerate(manifest["expected_scene_matrix"], 1):
            run_dir = output / "runs" / f"{index:04d}-{item['scene_id']}-{item['method']}"
            receipt = run_dir / "completed.json"
            if receipt.exists():
                saved = json.loads(receipt.read_text())
                if saved.get("item") != item or saved.get("artifact_hash") != _artifact_hashes(run_dir):
                    raise ValueError(f"completed evaluation run changed: {run_dir}")
                episodes.append(saved["episode"])
                continue
            if run_dir.exists():
                attempts = output / "attempts"
                attempts.mkdir(exist_ok=True)
                run_dir.rename(attempts / f"{run_dir.name}-{time.time_ns()}")
            run_dir.mkdir()
            metrics_path = run_dir / "replan_metrics.jsonl"
            started = time.time()
            command = runner_command(repo, item, run_dir, Path(args.setup_bash), models)
            completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False, pass_fds=(lock_fd,))
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
            if isinstance(result, dict) and result.get("simulation_health", {}).get("valid") is False:
                episode["instrumentation_error"] = True
            episode["simulation_health"] = result.get("simulation_health") if isinstance(result, dict) else None
            episode["run"] = {"index": index, "returncode": completed.returncode, "wall_seconds": time.time() - started, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]}
            episodes.append(episode)
            if result is not None and not episode["instrumentation_error"]:
                _write_json(receipt, {"item": item, "episode": episode, "artifact_hash": _artifact_hashes(run_dir)})
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
    expected_model_sha = {method: manifest["models"][method]["sha256"] for method in manifest["models"]}
    report["campaign"]["model_mismatches"] = sorted({episode["scene_id"] + ":" + episode["method"] for episode in episodes if episode["method"] in expected_model_sha and episode.get("model_sha") != expected_model_sha[episode["method"]]})
    report["campaign"]["identity_valid"] = not any((report["campaign"][key] for key in ("source_layout_mismatches", "source_manifest_mismatches", "config_mismatches", "model_mismatches")))
    report["campaign"]["instrumentation_errors"] = sorted({episode["scene_id"] + ":" + episode["method"] for episode in episodes if episode.get("instrumentation_error", False)})
    report["campaign"]["data_valid"] = report["campaign"]["identity_valid"] and not report["campaign"]["instrumentation_errors"]
    if not report["campaign"]["data_valid"]:
        reason = "instrumentation_error" if report["campaign"]["instrumentation_errors"] else "source_or_model_identity_mismatch"
        for environment in [*report.get("environments", {}).values(), *report.get("families", {}).values()]:
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
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--setup-bash", required=True)
    parser.add_argument("--bc-model", "--bc-policy", dest="bc_model")
    parser.add_argument("--cost-model", "--cost-policy", dest="cost_model")
    parser.add_argument("--closed-loop-model", "--closed-loop-policy", dest="closed_loop_model")
    parser.add_argument("--set-model", dest="set_model")
    parser.add_argument("--objective-model", dest="objective_model")
    parser.add_argument("--protocol", choices=("legacy", "benchmark_aligned_v1"), default="legacy")
    parser.add_argument("--methods", nargs="+", choices=(*ALIGNED_METHODS, "closed_loop"))
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--families", nargs="+", choices=("unknown_dynamic", "static_forest", "known_dynamic"))
    parser.add_argument("--shuffle-seed", type=int, default=0)
    parser.add_argument("--report-seed", type=int, default=0)
    return run_campaign(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
