#!/usr/bin/env python3
"""Run isolated calibration capture workers (launches Docker only when invoked)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

DRIVER = Path(__file__).resolve()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_identity(image):
    result = subprocess.run(["docker", "image", "inspect", image], check=False, capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        raise ValueError(f"docker image is unavailable: {image}")
    try:
        item = json.loads(result.stdout)[0]
    except (ValueError, IndexError, TypeError) as error:
        raise ValueError("docker image inspect returned invalid JSON") from error
    actual = item.get("Id")
    if not isinstance(actual, str) or not actual:
        raise ValueError("docker image has no immutable ID")
    return {"requested": image, "id": actual, "repo_digests": item.get("RepoDigests", [])}


def job_matrix(seeds, families):
    return [{"seed": seed, "families": list(families)} for seed in seeds]


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _quantiles(values):
    values = sorted(values)
    if not values:
        return {"p50": None, "p95": None, "p99": None}
    def percentile(rank):
        position = (len(values) - 1) * rank
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    return {"p50": percentile(0.50), "p95": percentile(0.95), "p99": percentile(0.99)}


def _flight_metrics(output, expected_flights=None):
    flights = []
    for result_path in sorted(output.glob("train/seed*/runs/*/result.json")):
        result = _load_json(result_path)
        if not isinstance(result, dict):
            flights.append({"path": str(result_path), "rtf": None, "rtf_error": "missing result"})
            continue
        samples = ((result.get("ground_truth") or {}).get("collision") or {}).get("min_clearance_samples")
        points = [(item.get("sim_time"), item.get("receipt_time")) for item in samples or []
                  if isinstance(item, dict)]
        valid = (len(points) >= 2 and all(_number(sim) and _number(receipt)
                                          for sim, receipt in points))
        if valid:
            sim_values, receipt_values = zip(*points)
            sim_span = max(sim_values) - min(sim_values)
            receipt_span = max(receipt_values) - min(receipt_values)
            valid = (_number(sim_span) and _number(receipt_span) and sim_span > 0 and receipt_span > 0 and all(
                later_sim >= earlier_sim and later_receipt >= earlier_receipt
                for (earlier_sim, earlier_receipt), (later_sim, later_receipt) in zip(points, points[1:])))
        elapsed = result.get("elapsed_sec")
        flights.append({"path": str(result_path), "success": bool(result.get("success")),
                        "sample_span_sec": (receipt_span if valid else None),
                        "elapsed_sec": elapsed if _number(elapsed) else None,
                        "sample_coverage": (receipt_span / elapsed if valid and _number(elapsed) and elapsed > 0 else None),
                        "rtf": (sim_span / receipt_span) if valid else None,
                        "rtf_error": None if valid else "missing, reset, or nonpositive timing samples"})
    metrics_paths = sorted(output.glob("train/seed*/runs/*/replan_metrics.jsonl"))
    attempted = successful = 0
    latencies = []
    successful_latencies = []
    metric_errors = []
    records_by_file = {}
    for path in metrics_paths:
        result = _load_json(path.parent / "result.json")
        start = result.get("goal_sent_wall_unix") if isinstance(result, dict) else None
        end = result.get("observation_end_wall_unix") if isinstance(result, dict) else None
        windowed = _number(start) and _number(end) and end >= start
        if not windowed:
            metric_errors.append(f"{path}: missing valid goal observation time window")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            metric_errors.append(f"{path}: {error}")
            continue
        records_by_file[str(path)] = 0
        for number, line in enumerate(lines, 1):
            try:
                item = json.loads(line)
                wall_time = item.get("wall_unix_time")
                if not _number(wall_time):
                    if item.get("planning_attempted") is True:
                        metric_errors.append(f"{path}:{number}: attempted record has invalid wall_unix_time")
                    continue
                if windowed and (wall_time < start or wall_time > end):
                    continue
                if not windowed:
                    continue
                if item.get("planning_attempted") is True:
                    records_by_file[str(path)] += 1
                    attempted += 1
                    latency = item.get("total_ms")
                    if not _number(latency) or latency < 0:
                        metric_errors.append(f"{path}:{number}: attempted record has invalid total_ms")
                    else:
                        latency = float(latency)
                        latencies.append(latency)
                        if item.get("success") is True:
                            successful_latencies.append(latency)
                    successful += int(item.get("success") is True)
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as error:
                metric_errors.append(f"{path}:{number}: {error}")
    result_paths = sorted(output.glob("train/seed*/runs/*/result.json"))
    timeouts = sum(1 for result_path in result_paths
                   if isinstance(_load_json(result_path), dict) and
                   (_load_json(result_path).get("error") == "observation timeout: goal_reached was not received"))
    for result_path in result_paths:
        if isinstance(_load_json(result_path), dict) and _load_json(result_path).get("instrumentation_error"):
            metric_errors.append(f"{result_path}: instrumentation_error")
        metric_path = result_path.with_name("replan_metrics.jsonl")
        if metric_path.is_file() and records_by_file.get(str(metric_path), 0) == 0:
            metric_errors.append(f"{metric_path}: no in-window planning_attempted records")
        elif expected_flights is not None and not metric_path.is_file():
            metric_errors.append(f"{metric_path}: missing metrics file")
    expected = expected_flights if expected_flights is not None else len(result_paths)
    if len(result_paths) < expected:
        metric_errors.append(f"missing metrics file/result evidence for {expected - len(result_paths)} expected flights")
    return {"coverage": {"flights": len(flights), "expected_flights": expected,
                          "rtf_valid": sum(f["rtf"] is not None for f in flights),
                          "metrics_files": len(metrics_paths), "metrics_records": attempted,
                          "complete": len(flights) == expected and sum(f["rtf"] is not None for f in flights) == expected and
                                      len(metrics_paths) == expected and all(value > 0 for value in records_by_file.values())},
            "flights": flights,
            "planning_latency_ms": {"attempted": attempted, "successful": successful,
                                     "records_with_latency": len(latencies),
                                     "mean": (sum(latencies) / len(latencies)) if latencies else None,
                                     **_quantiles(latencies),
                                     "successful_stats": {"count": len(successful_latencies), **_quantiles(successful_latencies)}},
            "timeout_rate": {"timeouts": timeouts, "flights": len(flights),
                             "rate": timeouts / len(flights) if flights else None},
            "errors": metric_errors}


def _worker(job, args, image, output, started):
    seed = job["seed"]
    worker_dir = output / "train" / f"seed{seed}"
    worker_dir.parent.mkdir(parents=True, exist_ok=True)
    log_path = output / "logs" / f"seed{seed}.log"
    experiment_id = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:10]
    command = ["docker", "run", "--rm", "--name", f"sando-calibration-{experiment_id}-{seed}",
               "--gpus", "all",
               "--cpus", str(args.cpus_per_worker), "--shm-size", "1g",
               "--env", "HEADLESS=1", "--env", "SANDO_AMPL_MODE=persistent",
               "--env", "NVIDIA_DRIVER_CAPABILITIES=all",
               "--env", f"ROS_DOMAIN_ID={100 + seed}",
               "--mount", f"type=bind,src={args.uuid_file.resolve()},dst=/run/secrets/ampl_uuid,readonly",
               "--mount", f"type=bind,src={output.resolve()},dst=/results",
               image["id"], "bash", "-lc"]
    if args.cpuset_cpus:
        command[2:2] = ["--cpuset-cpus", args.cpuset_cpus]
    resource_path = output / "logs" / f"seed{seed}.resources.json"
    inner = ("source /root/sando_ws/install/setup.bash; "
             "python3 /root/sando_ws/src/sando/scripts/capture_integer_learning_campaign.py "
             f"--output /results/train/seed{seed} --setup-bash /root/sando_ws/install/setup.bash "
             f"--split train --round 0 --seeds {seed} --counts 50 --protocol benchmark_aligned_v1 "
             f"--scene-families {shlex.join(job['families'])} --capture-capacity 5"
             + (" --replan-metrics" if args.replan_metrics else "")
             + "; rc=$?; if [ -r /sys/fs/cgroup/memory.peak ]; then peak=$(cat /sys/fs/cgroup/memory.peak); source_name=cgroup_v2_memory.peak; "
             + "elif [ -r /sys/fs/cgroup/memory/memory.max_usage_in_bytes ]; then peak=$(cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes); source_name=cgroup_v1_memory.max_usage_in_bytes; "
             + "else peak=; source_name=unavailable; fi; peak_value=${peak:-null}; "
             + f"printf '{{\"schema_version\":1,\"memory_peak_bytes\":%s,\"memory_source\":\"%s\",\"capture_returncode\":%s}}\\n' \"$peak_value\" \"$source_name\" \"$rc\" > /results/logs/seed{seed}.resources.json; chmod -R a+rX /results/train/seed{seed}; exit $rc")
    began = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command + [inner], stdout=log, stderr=subprocess.STDOUT, check=False)
    ended = time.time()
    status = {"seed": seed, "families": job["families"], "returncode": completed.returncode,
              "started_unix": began, "ended_unix": ended, "wall_seconds": ended - began,
              "output": str(worker_dir), "completed": (worker_dir / "output.json").is_file(),
              "resource": _load_json(resource_path), "resource_path": str(resource_path)}
    (output / "logs" / f"seed{seed}.status.json").write_text(json.dumps(status, indent=2) + "\n")
    return status


def run(args):
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if not args.uuid_file.is_file():
        raise ValueError(f"UUID file is missing: {args.uuid_file}")
    if len(set(args.seeds)) != len(args.seeds) or any(seed < 0 or seed > 39 for seed in args.seeds):
        raise ValueError("seeds must be unique train seeds in 0..39")
    if args.workers not in (1, 2, 4) or args.cpus_per_worker <= 0:
        raise ValueError("workers must be 1, 2, or 4 and cpus-per-worker must be positive")
    image = image_identity(args.image)
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    jobs = job_matrix(args.seeds, args.families)
    config = {"image": image, "driver_sha256": sha256(DRIVER),
              "clock_start_utc": datetime.now(timezone.utc).isoformat(),
              "args": {"workers": args.workers, "seeds": args.seeds, "families": args.families,
                        "cpus_per_worker": args.cpus_per_worker, "cpuset_cpus": args.cpuset_cpus,
                        "replan_metrics": args.replan_metrics,
                        "gpus": "all", "headless": True, "nvidia_driver_capabilities": "all",
                        "uuid_file": str(args.uuid_file.resolve())},
              "job_matrix": jobs}
    (output / "run_config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    started = time.time(); statuses = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_worker, job, args, image, output, started) for job in jobs]
        for future in as_completed(futures): statuses.append(future.result())
    ended = time.time()
    config["clock_end_utc"] = datetime.now(timezone.utc).isoformat()
    config["outer_wall_seconds"] = ended - started
    config["jobs"] = sorted(statuses, key=lambda item: item["seed"])
    config["completed_jobs"] = sum(item["completed"] for item in statuses)
    config["valid_captured_jobs"] = sum(item["completed"] and item["returncode"] == 0 for item in statuses)
    from measure_integer_throughput import measure_root
    config["throughput"] = measure_root(output)
    config["throughput"]["capture_wall_interval_sec"] = config["throughput"]["wall_interval_sec"]
    config["throughput"]["wall_interval_sec"] = ended - started
    config["throughput"]["wall_hours"] = (ended - started) / 3600
    config["throughput"]["instances_per_wall_hour"] = (
        config["throughput"]["qualified_retained_instances"] * 3600 / (ended - started))
    config["throughput"]["all_valid_instances_per_wall_hour"] = (
        config["throughput"]["all_valid_retained_instances"] * 3600 / (ended - started))
    config["metrics"] = _flight_metrics(output, len(jobs) * len(args.families))
    resources = [item["resource"] for item in statuses
                 if isinstance(item.get("resource"), dict) and
                 _number(item["resource"].get("memory_peak_bytes")) and
                 item["resource"].get("memory_peak_bytes") > 0]
    config["memory"] = {"source": "true per-container cgroup peak",
                         "workers_with_measurement": len(resources),
                         "peaks_bytes": [item.get("memory_peak_bytes") for item in resources],
                         "errors": [item.get("resource") for item in statuses
                                    if not isinstance(item.get("resource"), dict) or
                                    not _number(item["resource"].get("memory_peak_bytes")) or
                                    item["resource"].get("memory_peak_bytes") <= 0]}
    config["instrumentation_complete"] = (
        not config["memory"]["errors"] and
        (not args.replan_metrics or
         config["metrics"]["coverage"]["complete"] and
         not config["metrics"]["errors"]))
    (output / "run_config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    return 0 if config["valid_captured_jobs"] == len(jobs) and config["instrumentation_complete"] else 2


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=1)
    parser.add_argument("--seeds", nargs="+", type=int, default=[30, 31, 32, 33])
    parser.add_argument("--families", nargs="+", choices=("unknown_dynamic", "static_forest"), default=["unknown_dynamic", "static_forest"])
    parser.add_argument("--uuid-file", type=Path, default=Path.home() / ".config/ampl/uuid")
    parser.add_argument("--cpus-per-worker", type=int, default=8)
    parser.add_argument("--cpuset-cpus", help="Shared CPU set for every arm, e.g. 4-19,24-39")
    parser.add_argument("--replan-metrics", action="store_true",
                        help="opt in to per-flight replan_metrics.jsonl instrumentation")
    try:
        return run(parser.parse_args(argv))
    except Exception as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
