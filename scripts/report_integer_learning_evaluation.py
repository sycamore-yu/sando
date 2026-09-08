#!/usr/bin/env python3
"""Report paired final evaluation results without treating trajectory frames as samples.

Input is JSONL with one record per ``(scene_id, method)`` episode.  Required
fields are ``scene_id``, ``method`` (original, previous, bc, cost, or
closed_loop), ``environment`` (static or dynamic), ``split``,
``planning_latency_ms`` (the complete list of planning times for that episode),
``success`` and ``task_duration_s`` for successful episodes.  ``collision``,
``tracking_error`` and ``constraint_violation`` are optional evidence fields;
they are reported only when present.  Failed episodes use a 100 second cap
when ``task_duration_s`` is supplied.  Bootstrap resampling is over paired
scene summaries, with a fixed seed, never over latency frames.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

METHODS = ("original", "previous", "bc", "cost", "closed_loop")
ENVIRONMENTS = ("static", "dynamic")
FAILURE_CAP_SECONDS = 100.0


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite numeric")
    return float(value)


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("evaluation record must be an object")
    for key in ("scene_id", "method", "environment", "split"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ValueError(f"{key} must be nonempty")
    if record["method"] not in METHODS or record["environment"] not in ENVIRONMENTS:
        raise ValueError("unknown method or environment")
    if record["split"] != "test" or isinstance(record.get("seed"), bool) or not isinstance(record.get("seed"), int) or not 200 <= record["seed"] <= 229:
        raise ValueError("evaluation records must use locked test seeds 200..229")
    match = re.search(r"^n(50|100|200)-d([0-9]+(?:\.[0-9]+)?)-seed(\d+)$", record["scene_id"])
    if not match or int(match.group(3)) != record["seed"] or not isinstance(record.get("num_obstacles"), int) or record["num_obstacles"] not in (50, 100, 200):
        raise ValueError("scene_id, seed, and num_obstacles metadata do not match")
    if int(match.group(1)) != record["num_obstacles"] or not isinstance(record.get("dynamic_ratio"), (int, float)) or isinstance(record["dynamic_ratio"], bool):
        raise ValueError("scene count metadata does not match scene_id")
    dynamic_ratio = _number(record["dynamic_ratio"], "dynamic ratio")
    if dynamic_ratio not in (0.0, 0.65) or (record["environment"] == "static" and dynamic_ratio != 0.0) or (record["environment"] == "dynamic" and dynamic_ratio != 0.65) or abs(dynamic_ratio - float(match.group(2))) > 1e-9:
        raise ValueError("environment and dynamic ratio metadata do not match")
    if not isinstance(record.get("planning_latency_ms"), list):
        raise ValueError("planning_latency_ms must contain all episode planning times")
    latency = [_number(value, "planning latency") for value in record["planning_latency_ms"]]
    if any(value < 0 for value in latency):
        raise ValueError("planning latency cannot be negative")
    if not isinstance(record.get("success"), bool):
        raise ValueError("success must be boolean")
    result = dict(record)
    result["planning_latency_ms"] = latency
    if "task_duration_s" in result and result["task_duration_s"] is not None:
        result["task_duration_s"] = _number(result["task_duration_s"], "task duration")
        if result["success"] and not 0.0 < result["task_duration_s"] <= FAILURE_CAP_SECONDS:
            raise ValueError("successful task duration must be in (0,100]")
    for key in ("tracking_error", "constraint_violation"):
        if key in result and result[key] is not None:
            result[key] = _number(result[key], key)
    if "collision" in result and result["collision"] is not None and not isinstance(result["collision"], bool):
        raise ValueError("collision must be boolean")
    checks = result.get("constraint_checks", result.get("hard_constraint_checks"))
    if isinstance(checks, dict):
        accepted = checks.get("accepted", checks.get("accepted_trajectories"))
        checked = checks.get("checked", checks.get("accepted_trajectories_checked"))
        violations = checks.get("violations", checks.get("constraint_violations"))
        result["constraint_checks"] = {"checked": checked, "violations": violations}
        result["constraint_checks"]["accepted"] = accepted
    else:
        result["constraint_checks"] = {"accepted": None, "checked": None, "violations": None}
        accepted = checked = violations = None
    if accepted is not None and (isinstance(accepted, bool) or not isinstance(accepted, int) or accepted < 0):
        raise ValueError("constraint_checks accepted count is invalid")
    if checked is not None and (isinstance(checked, bool) or not isinstance(checked, int) or checked < 0):
        raise ValueError("constraint_checks checked count is invalid")
    if violations is not None and (isinstance(violations, bool) or not isinstance(violations, int) or violations < 0):
        raise ValueError("constraint_checks violation count is invalid")
    if None not in (accepted, checked, violations) and (checked != accepted or violations > checked):
        raise ValueError("constraint_checks coverage does not match accepted count")
    return result


def load_records(paths: str | Path | Iterable[str | Path]) -> list[dict[str, Any]]:
    paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
    records = []
    for path in paths:
        with Path(path).open() as stream:
            for line_number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        records.append(validate_record(json.loads(line)))
                    except (ValueError, json.JSONDecodeError) as error:
                        raise ValueError(f"{path}:{line_number}: {error}") from error
    return records


def _summary_values(records: list[dict[str, Any]]) -> dict[str, Any]:
    latency_frames = np.concatenate([np.asarray(record["planning_latency_ms"], dtype=float) for record in records]) if records else np.asarray([], dtype=float)
    episode_medians = [float(np.median(record["planning_latency_ms"])) for record in records
                       if record["planning_latency_ms"]]
    successes = [1.0 if record["success"] else 0.0 for record in records]
    flights = []
    missing_flight_duration = 0
    for record in records:
        if not record["success"]:
            flights.append(FAILURE_CAP_SECONDS)
        elif record.get("task_duration_s") is not None:
            flights.append(float(record["task_duration_s"]))
        else:
            missing_flight_duration += 1
    result = {
        "n": len(records),
        "latency_ms": {"p50": float(np.percentile(latency_frames, 50)) if len(latency_frames) else None, "p95": float(np.percentile(latency_frames, 95)) if len(latency_frames) else None, "p99": float(np.percentile(latency_frames, 99)) if len(latency_frames) else None, "frame_count": int(len(latency_frames)), "episode_median_median": float(np.median(episode_medians)) if episode_medians else None, "episodes_with_latency": len(episode_medians)},
        "success_rate": float(np.mean(successes)),
        "flight_time_s_failure_capped": {"available": bool(flights) and missing_flight_duration == 0, "n": len(flights), "missing_success_duration": missing_flight_duration, "median": float(np.median(flights)) if flights and missing_flight_duration == 0 else None},
    }
    evidence = {}
    for key in ("collision", "tracking_error", "constraint_violation"):
        values = [record[key] for record in records if key in record and record[key] is not None]
        if not values:
            evidence[key] = {"available": False, "n": 0}
        elif key == "collision":
            evidence[key] = {"available": True, "n": len(values), "rate": float(np.mean(values))}
        else:
            evidence[key] = {"available": True, "n": len(values), "median": float(np.median(values))}
    check_records = [record["constraint_checks"] for record in records]
    complete_checks = [check for check in check_records if None not in (check.get("accepted"), check.get("checked"), check.get("violations")) and check["checked"] == check["accepted"]]
    checked = sum(check["checked"] for check in complete_checks)
    violations = sum(check["violations"] for check in complete_checks)
    evidence["hard_constraints"] = {"available": len(complete_checks) == len(records) and bool(records), "checked": checked, "accepted": sum(check.get("accepted", 0) or 0 for check in check_records), "violations": violations, "missing_coverage": len(records) - len(complete_checks)}
    result["evidence"] = evidence
    request_count = sum(record.get("planning_request_count", 0) for record in records)
    accepted_count = sum((record.get("constraint_checks") or {}).get("accepted", 0) or 0 for record in records)
    result["planning_outcomes"] = {
        "request_count": request_count,
        "failure_rate": sum(record.get("planning_failure_count", 0) for record in records) / request_count if request_count else None,
        "request_fallback_rate": sum(record.get("fallback_request_count", 0) for record in records) / request_count if request_count else None,
        "accepted_fallback_rate": sum(record.get("accepted_fallback_count", 0) for record in records) / accepted_count if accepted_count and all("accepted_fallback_count" in record for record in records) else None,
        "component_times_non_additive": True,
        "component_totals_available": all("planning_components_ms" in record for record in records),
        "component_totals_ms": {
            key: sum(record.get("planning_components_ms", {}).get(key, 0.0) for record in records)
            for key in ("parallel_ms", "cancel_drain_ms", "ranking_ms", "qp_ms", "fallback_ms", "model_prepare_ms", "validation_ms", "decomp_ms")
        },
    }
    return result


def paired_bootstrap(candidate: Iterable[float], baseline: Iterable[float], statistic: Callable[[np.ndarray], float] = np.median, seed: int = 0, samples: int = 400) -> dict[str, Any]:
    candidate = np.asarray(list(candidate), dtype=float)
    baseline = np.asarray(list(baseline), dtype=float)
    if candidate.size == 0 or candidate.size != baseline.size:
        return {"available": False, "n": int(candidate.size), "estimate": None, "ci95": None}
    differences = candidate - baseline
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, candidate.size, size=(samples, candidate.size))
    boot = np.asarray([statistic(differences[index]) for index in indices], dtype=float)
    return {"available": True, "n": int(candidate.size), "estimate": float(statistic(differences)), "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]}


def paired_latency_bootstrap(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]], percentile: float, seed: int = 0, ratio: bool = False, samples: int = 400) -> dict[str, Any]:
    if not candidate or len(candidate) != len(baseline) or any(
            not record["planning_latency_ms"] for record in candidate + baseline):
        return {"available": False, "n": len(candidate), "estimate": None, "ci95": None,
                "reason": "missing_episode_latency"}
    def statistic(indices: np.ndarray) -> float:
        candidate_frames = np.concatenate([np.asarray(candidate[index]["planning_latency_ms"]) for index in indices])
        baseline_frames = np.concatenate([np.asarray(baseline[index]["planning_latency_ms"]) for index in indices])
        c = float(np.percentile(candidate_frames, percentile)); b = float(np.percentile(baseline_frames, percentile))
        if ratio:
            return c / b if b > 0 else float("nan")
        return c - b
    indices = np.arange(len(candidate))
    point = statistic(indices)
    if not math.isfinite(point):
        return {"available": False, "n": len(candidate), "estimate": None, "ci95": None}
    rng = np.random.default_rng(seed)
    boot = np.asarray([statistic(rng.integers(0, len(candidate), size=len(candidate))) for _ in range(samples)])
    boot = boot[np.isfinite(boot)]
    return {"available": len(boot) > 0, "n": len(candidate), "estimate": point, "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))] if len(boot) else None, "statistic": f"pooled_p{int(percentile)}_{'ratio' if ratio else 'difference'}"}


def _scene_map(records: list[dict[str, Any]], environment: str, method: str) -> dict[str, dict[str, Any]]:
    result = {}
    for record in records:
        if record["environment"] != environment or record["method"] != method:
            continue
        if record["scene_id"] in result:
            raise ValueError(f"duplicate episode for {environment}/{method}/{record['scene_id']}")
        result[record["scene_id"]] = record
    return result


def _gate(method: str, candidate: dict[str, Any], baseline: dict[str, Any], paired: dict[str, Any], scene_match: bool) -> dict[str, Any]:
    checks = {}
    if not scene_match or candidate["n"] < 2 or baseline["n"] < 2:
        return {"status": "insufficient", "checks": checks, "reason": "missing_or_mismatched_scene_pairs"}
    latency_ratio = paired["latency_p50_ratio"]
    p95_difference = paired["latency_p95_difference_ms"]
    checks["median_latency_ratio_le_0_9"] = {"available": latency_ratio["available"], "value": latency_ratio.get("estimate"), "ci95": latency_ratio.get("ci95"), "pass": latency_ratio["available"] and latency_ratio["estimate"] <= .9 and latency_ratio["ci95"][1] < 1.0}
    checks["p95_latency_le_baseline"] = {"available": p95_difference["available"], "value": p95_difference.get("estimate"), "ci95": p95_difference.get("ci95"), "pass": p95_difference["available"] and p95_difference["estimate"] <= 0.0}
    decrement = baseline["success_rate"] - candidate["success_rate"]
    success = paired["success_decrement"]
    checks["success_decrement_le_0_05"] = {"available": success["available"], "value": decrement, "ci95": success.get("ci95"), "pass": success["available"] and decrement <= .05}
    flight = paired.get("common_success_flight_time_ratio", {})
    checks["common_success_flight_time_ratio_le_1_05"] = {"available": flight.get("available", False), "value": flight.get("estimate"), "ci95": flight.get("ci95"), "pass": flight.get("available", False) and flight["estimate"] <= 1.05}
    constraints = candidate["evidence"]["hard_constraints"]
    base_constraints = baseline["evidence"]["hard_constraints"]
    checks["hard_constraints_checked_without_violations"] = {"available": constraints["available"] and base_constraints["available"], "value": constraints["violations"], "pass": constraints["available"] and base_constraints["available"] and constraints["violations"] == 0 and base_constraints["violations"] == 0}
    collision = candidate["evidence"]["collision"]; base_collision = baseline["evidence"]["collision"]
    checks["collision_evidence_complete"] = {"available": collision["available"] and base_collision["available"] and collision["n"] == candidate["n"] and base_collision["n"] == baseline["n"], "value": collision.get("rate"), "pass": collision["available"] and base_collision["available"] and collision["n"] == candidate["n"] and base_collision["n"] == baseline["n"]}
    tracking = candidate["evidence"]["tracking_error"]; base_tracking = baseline["evidence"]["tracking_error"]
    checks["tracking_evidence_complete"] = {"available": tracking["available"] and base_tracking["available"] and tracking["n"] == candidate["n"] and base_tracking["n"] == baseline["n"], "value": tracking.get("median"), "pass": tracking["available"] and base_tracking["available"] and tracking["n"] == candidate["n"] and base_tracking["n"] == baseline["n"]}
    missing = [name for name, check in checks.items() if not check["available"]]
    return {"status": "insufficient" if missing else ("pass" if all(check["pass"] for check in checks.values()) else "fail"), "checks": checks, "reason": "missing_required_evidence" if missing else None}


def _summarize_groups(records: list[dict[str, Any]], environment: str, seed: int = 0) -> dict[str, Any]:
    groups = {method: _scene_map(records, environment, method) for method in METHODS}
    summaries = {method: _summary_values([groups[method][scene] for scene in sorted(groups[method])]) for method in METHODS if groups[method]}
    baseline = groups["original"]
    methods = {}
    for method, current in groups.items():
        if not current:
            continue
        if method == "original":
            methods[method] = summaries[method]
            continue
        if not baseline:
            methods[method] = {**summaries[method], "paired_to_original": {}, "gate_vs_original": {"status": "insufficient", "checks": {}, "reason": "missing_original_group"}, "n_common_scenes": 0, "missing_scenes": [], "extra_scenes": sorted(current)}
            continue
        common = sorted(set(current) & set(baseline))
        scene_match = bool(baseline) and set(current) == set(baseline)
        candidate_summary = summaries[method]
        base_common = [baseline[scene] for scene in common]
        cand_common = [current[scene] for scene in common]
        paired = {
            "latency_p50_ratio": paired_latency_bootstrap(cand_common, base_common, 50, seed=seed, ratio=True),
            "latency_p95_difference_ms": paired_latency_bootstrap(cand_common, base_common, 95, seed=seed + 1),
            "latency_p99_difference_ms": paired_latency_bootstrap(cand_common, base_common, 99, seed=seed + 2),
            "success_decrement": paired_bootstrap([float(not x["success"]) for x in cand_common], [float(not x["success"]) for x in base_common], statistic=np.mean, seed=seed + 3),
        }
        successful = [(x, y) for x, y in zip(cand_common, base_common) if x["success"] and y["success"] and x.get("task_duration_s") is not None and y.get("task_duration_s") is not None]
        if successful:
            def flight_stat(indices):
                candidate_times = np.asarray([successful[index][0]["task_duration_s"] for index in indices])
                baseline_times = np.asarray([successful[index][1]["task_duration_s"] for index in indices])
                return float(np.median(candidate_times) / np.median(baseline_times))
            point = flight_stat(np.arange(len(successful))); rng = np.random.default_rng(seed + 4)
            boot = np.asarray([flight_stat(rng.integers(0, len(successful), size=len(successful))) for _ in range(400)])
            ratio = {"available": True, "n": len(successful), "estimate": point, "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))], "statistic": "pooled_success_flight_median_ratio"}
        else:
            ratio = {"available": False, "n": 0, "estimate": None, "ci95": None}
        paired["common_success_flight_time_ratio"] = ratio
        methods[method] = {**candidate_summary, "paired_to_original": paired, "gate_vs_original": _gate(method, candidate_summary, summaries["original"], paired, scene_match), "n_common_scenes": len(common), "missing_scenes": sorted(set(baseline) - set(current)), "extra_scenes": sorted(set(current) - set(baseline))}
    return {"n_scenes_by_method": {method: len(groups[method]) for method in METHODS}, "methods": methods}


def summarize_environment(records: list[dict[str, Any]], environment: str, seed: int = 0) -> dict[str, Any]:
    result = _summarize_groups(records, environment, seed)
    counts = sorted({record["num_obstacles"] for record in records if record["environment"] == environment})
    result["by_num_obstacles"] = {str(count): _summarize_groups([record for record in records if record["environment"] == environment and record["num_obstacles"] == count], environment, seed + count) for count in counts}
    return result


def make_report(records: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    records = [validate_record(record) for record in records]
    return {"schema_version": 1, "bootstrap": {"seed": seed, "unit": "scene", "confidence": .95}, "environments": {environment: summarize_environment(records, environment, seed + index * 100) for index, environment in enumerate(ENVIRONMENTS)}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    report = make_report(load_records(args.input), args.seed)
    with Path(args.output).open("x") as stream:
        json.dump(report, stream, allow_nan=False, indent=2)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
