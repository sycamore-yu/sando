#!/usr/bin/env python3
"""Report quality and timing from frozen integer-planning replay JSONL.

Replay rows describe one frozen planning instance evaluated by five methods.
This report keeps those instance rows as the unit of quality accounting and
keeps all method timings inside their scene when bootstrapping.  It does not
turn replay timings into a full-planner latency gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

METHODS = ("original", "previous", "bc", "cost", "closed_loop")
SCENE_RE = re.compile(r"^n(?P<count>[0-9]+)-d(?P<ratio>0|0\.65)-seed(?P<seed>[0-9]+)$")


def _finite(value: Any, name: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    if isinstance(value, list):
        for index, child in enumerate(value):
            _finite(child, f"{name}[{index}]")
    elif isinstance(value, dict):
        for key, child in value.items():
            _finite(child, f"{name}.{key}")


def _number(value: Any, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite numeric")
    result = float(value)
    if nonnegative and result < 0:
        raise ValueError(f"{name} must be nonnegative")
    return result


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _assignment(value: Any, name: str, *, allow_empty: bool = True,
                allow_none: bool = True) -> None:
    if value is None:
        if not allow_none:
            raise ValueError(f"{name} must be an integer array")
        return
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError(f"{name} must be null or an integer array")
    if not value and allow_empty:
        return
    if len(value) != 5 or any(item < 0 or item > 2 for item in value):
        raise ValueError(f"{name} must be empty or a length-five array with entries in 0..2")


# Keep the reporter aligned with sando_learning::kResidualTolerance.
RESIDUAL_TOLERANCE = 2e-6


def _residuals(value: Any, name: str, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, dict) or not isinstance(value.get("valid"), bool):
        raise ValueError(f"{name} must contain boolean valid")
    for key in ("bounds", "constraints", "integrality", "objective"):
        if key not in value:
            raise ValueError(f"{name}.{key} is required")
        _number(value[key], f"{name}.{key}", nonnegative=True)
    if value["valid"]:
        for key in ("bounds", "constraints", "integrality", "objective"):
            if float(value[key]) > RESIDUAL_TOLERANCE:
                raise ValueError(f"{name}.valid is inconsistent with {key} exceeding residual tolerance")


def _same_time(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-9)


def _at_least(actual: float, expected: float) -> bool:
    return actual + max(1e-9, 1e-7 * max(actual, expected)) >= expected


def _validate_attempt(value: Any, name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if isinstance(value.get("status"), bool) or not isinstance(value.get("status"), int):
        raise ValueError(f"{name}.status must be an integer")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in ("qp", "miqp", "original"):
        raise ValueError(f"{name}.kind is invalid")
    for key in ("solve_attempted", "accepted", "fallback"):
        _bool(value.get(key), f"{name}.{key}")
    if kind == "original":
        _assignment(value.get("assignment"), f"{name}.assignment", allow_empty=False)
        if value.get("assignment") is not None:
            raise ValueError(f"{name}.original assignment must be null")
    else:
        _assignment(value.get("assignment"), f"{name}.assignment",
                    allow_empty=kind == "miqp", allow_none=kind == "miqp")
    for key in ("objective", "raw_objective"):
        if value.get(key) is not None:
            _number(value[key], f"{name}.{key}")
    _residuals(value.get("residuals"), f"{name}.residuals")
    _residuals(value.get("original_residuals"), f"{name}.original_residuals")
    for key in ("wall_seconds", "backend_seconds", "prepare_seconds", "adapter_seconds"):
        _number(value.get(key), f"{name}.{key}", nonnegative=True)
    if not isinstance(value.get("error"), str):
        raise ValueError(f"{name}.error must be a string")
    if not _at_least(value["wall_seconds"], value["prepare_seconds"]) or not _at_least(value["wall_seconds"], value["adapter_seconds"]):
        raise ValueError(f"{name}.wall_seconds is less than a contained attempt component")
    if kind != "qp" and value.get("original_residuals") is not None:
        raise ValueError(f"{name}.original_residuals is only valid for qp")
    if value["status"] != 2:
        if value["solve_attempted"] is False and value["accepted"]:
            raise ValueError(f"{name}.accepted requires solve_attempted")
        if value.get("residuals") is not None or value.get("original_residuals") is not None:
            raise ValueError(f"{name}.nonoptimal attempts must not contain residuals")
        if value.get("objective") is not None or value.get("raw_objective") is not None:
            raise ValueError(f"{name}.nonoptimal attempts must not contain objectives")
    elif not value["solve_attempted"]:
        raise ValueError(f"{name}.optimal status requires solve_attempted")
    if value["accepted"]:
        if value["status"] != 2 or not value["solve_attempted"]:
            raise ValueError(f"{name}.accepted requires optimal attempted solve")
        _residuals(value.get("residuals"), f"{name}.residuals", required=True)
        if not value["residuals"]["valid"]:
            raise ValueError(f"{name}.accepted requires valid residuals")
        if kind == "qp":
            if value.get("original_residuals") is None:
                raise ValueError(f"{name}.accepted qp requires original_residuals")
            _residuals(value["original_residuals"], f"{name}.original_residuals", required=True)
            if not value["original_residuals"]["valid"]:
                raise ValueError(f"{name}.accepted qp requires valid original_residuals")
        if value.get("objective") is None or value.get("raw_objective") is None:
            raise ValueError(f"{name}.accepted requires objectives")


def _validate_method(value: Any, method: str, name: str) -> None:
    _assignment(value.get("chosen_assignment"), f"{name}.chosen_assignment")
    _bool(value.get("history_available"), f"{name}.history_available")
    fallback_used = _bool(value.get("fallback_used"), f"{name}.fallback_used")
    if method != "previous" and value["history_available"]:
        raise ValueError(f"{name}.history_available is only valid for previous")
    if not isinstance(value.get("fallback_reason"), str):
        raise ValueError(f"{name}.fallback_reason must be a string")
    proposed = value.get("proposed_assignments")
    if not isinstance(proposed, list):
        raise ValueError(f"{name}.proposed_assignments must be an array")
    for index, assignment in enumerate(proposed):
        _assignment(assignment, f"{name}.proposed_assignments[{index}]", allow_empty=False,
                    allow_none=False)
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError(f"{name}.attempts must be a nonempty array")
    for index, attempt in enumerate(attempts):
        _validate_attempt(attempt, f"{name}.attempts[{index}]")
    timing = value.get("timing")
    if not isinstance(timing, dict):
        raise ValueError(f"{name}.timing must be an object")
    for key in ("ranking_seconds", "backend_seconds", "prepare_seconds", "adapter_seconds",
                "fallback_seconds", "total_seconds"):
        _number(timing.get(key), f"{name}.timing.{key}", nonnegative=True)
    for key in ("backend_seconds", "prepare_seconds", "adapter_seconds"):
        expected = sum(float(attempt[key]) for attempt in attempts)
        if not _same_time(float(timing[key]), expected):
            raise ValueError(f"{name}.timing.{key} must equal attempt total")
    elapsed = float(timing["ranking_seconds"]) + sum(float(attempt["wall_seconds"]) for attempt in attempts)
    if not _at_least(float(timing["total_seconds"]), elapsed):
        raise ValueError(f"{name}.timing.total_seconds is less than ranking and attempt wall time")
    if any(not _at_least(float(timing["total_seconds"]), float(timing[key]))
           for key in ("backend_seconds", "prepare_seconds", "adapter_seconds", "fallback_seconds")):
        raise ValueError(f"{name}.timing.total_seconds is less than an attempt component total")

    accepted = [attempt for attempt in attempts if attempt["accepted"]]
    if len(accepted) > 1 or accepted and not attempts[-1]["accepted"]:
        raise ValueError(f"{name}.attempts continue after acceptance")
    success = bool(accepted)
    _assignment(value.get("chosen_assignment"), f"{name}.chosen_assignment",
                allow_empty=False, allow_none=not success)
    if not success and value.get("chosen_assignment") is not None:
        raise ValueError(f"{name}.chosen_assignment requires an accepted attempt")

    if method == "original":
        if proposed or fallback_used or value["fallback_reason"] or len(attempts) != 1:
            raise ValueError(f"{name}.original method has an illegal fallback or candidate path")
        if attempts[0]["kind"] != "original" or attempts[0]["fallback"]:
            raise ValueError(f"{name}.original method must contain one original attempt")
        if not _same_time(float(timing["fallback_seconds"]), 0.0):
            raise ValueError(f"{name}.original method has fallback timing")
        return

    if len(proposed) > 3 or len({tuple(item) for item in proposed}) != len(proposed):
        raise ValueError(f"{name}.proposed_assignments must be at most three unique candidates")
    qp_attempts = [attempt for attempt in attempts if attempt["kind"] == "qp"]
    miqp_attempts = [attempt for attempt in attempts if attempt["kind"] == "miqp"]
    if len(qp_attempts) + len(miqp_attempts) != len(attempts):
        raise ValueError(f"{name}.nonoriginal method has an illegal attempt kind")
    if attempts != qp_attempts + miqp_attempts or len(miqp_attempts) > 1:
        raise ValueError(f"{name}.fallback must be one final miqp attempt")
    if any(attempt["fallback"] for attempt in qp_attempts) or any(not attempt["fallback"] for attempt in miqp_attempts):
        raise ValueError(f"{name}.attempt fallback flags do not match kinds")
    if [attempt["assignment"] for attempt in qp_attempts] != proposed[:len(qp_attempts)]:
        raise ValueError(f"{name}.qp attempts must follow proposed candidates")
    qp_success = any(attempt["accepted"] for attempt in qp_attempts)
    if not qp_success and len(qp_attempts) != len(proposed):
        raise ValueError(f"{name}.fallback requires candidate exhaustion")
    if qp_success and len(qp_attempts) != len(attempts):
        raise ValueError(f"{name}.fallback follows accepted qp")
    if bool(miqp_attempts) != fallback_used or bool(miqp_attempts) == qp_success:
        raise ValueError(f"{name}.fallback path is inconsistent")
    if fallback_used and not value["fallback_reason"]:
        raise ValueError(f"{name}.fallback_used requires fallback_reason")
    if miqp_attempts:
        fallback_attempt = miqp_attempts[0]
        if not _at_least(float(timing["fallback_seconds"]), float(fallback_attempt["wall_seconds"])):
            raise ValueError(f"{name}.timing.fallback_seconds is less than fallback wall time")
    elif not _same_time(float(timing["fallback_seconds"]), 0.0):
        raise ValueError(f"{name}.timing.fallback_seconds requires a fallback attempt")


def validate_record(record: Any, row_number: int = 0) -> dict[str, Any]:
    """Validate one replay row and annotate its parsed scene group."""
    if not isinstance(record, dict):
        raise ValueError(f"row {row_number} must be an object")
    _finite(record, f"row {row_number}")
    if record.get("schema_version") != 1 or record.get("kind") != "sando_integer_replay":
        raise ValueError(f"row {row_number} has an unsupported schema")
    if not isinstance(record.get("excluded"), bool):
        raise ValueError(f"row {row_number}.excluded must be boolean")
    if record["excluded"]:
        if not isinstance(record.get("error"), str) or not record["error"]:
            raise ValueError(f"row {row_number} excluded rows require an error")
        return dict(record)
    for key in ("scene_id", "episode_id", "request_id", "factor_id", "source_id", "config_id"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ValueError(f"row {row_number}.{key} must be nonempty")
    match = SCENE_RE.fullmatch(record["scene_id"])
    if not match:
        raise ValueError(f"row {row_number}.scene_id is not an exact frozen scene id")
    count = int(match.group("count"))
    if count not in (50, 100, 200):
        raise ValueError(f"row {row_number}.scene_id has an unsupported obstacle count")
    ratio = float(match.group("ratio"))
    if f"n{count}-d{match.group('ratio')}-seed{int(match.group('seed'))}" != record["scene_id"]:
        raise ValueError(f"row {row_number}.scene_id is not canonical")
    methods = record.get("methods")
    if not isinstance(methods, dict) or set(methods) != set(METHODS):
        raise ValueError(f"row {row_number}.methods must contain exactly the five replay methods")
    for method in METHODS:
        value = methods[method]
        prefix = f"row {row_number}.methods.{method}"
        if not isinstance(value, dict) or value.get("method") != method:
            raise ValueError(f"{prefix} has an invalid method identity")
        _validate_method(value, method, prefix)
    result = dict(record)
    result["_scene_count"] = count
    result["_environment"] = "dynamic" if ratio == 0.65 else "static"
    result["_instance_id"] = (record["scene_id"], record["episode_id"],
                               record["request_id"], record["factor_id"])
    result["_source_id"] = record["source_id"]
    result["_config_id"] = record["config_id"]
    return result


def _excluded(row_number: int, error: str) -> dict[str, Any]:
    return {"schema_version": 1, "kind": "sando_integer_replay", "excluded": True,
            "line": row_number, "error": error}


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Load JSONL, retaining malformed, excluded, and duplicate rows as exclusions."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for row_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant {value}")))
                row = validate_record(raw, row_number)
                if not row.get("excluded", False):
                    identity = row["_instance_id"]
                    if identity in seen:
                        rows.append(_excluded(row_number, "duplicate_instance_id"))
                        continue
                    seen.add(identity)
                rows.append(row)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                rows.append(_excluded(row_number, str(error)))
    return rows


def load_instance_index(path: str | Path) -> dict[str, Any]:
    """Collect only identifiers from the original PlanningInstance JSONL."""
    digest = hashlib.sha256()
    identities: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    malformed: list[dict[str, Any]] = []
    with Path(path).open("rb") as stream:
        for row_number, raw_line in enumerate(stream, 1):
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant {value}")))
                if not isinstance(record, dict):
                    raise ValueError("instance must be an object")
                fields = ("scene_id", "episode_id", "request_id", "factor_id", "source_id", "config_id")
                if any(not isinstance(record.get(key), str) or not record[key] for key in fields):
                    raise ValueError("instance identifiers must be nonempty strings")
                match = SCENE_RE.fullmatch(record["scene_id"])
                if not match or int(match.group("count")) not in (50, 100, 200):
                    raise ValueError("instance scene_id is not an exact supported scene id")
                if f"n{int(match.group('count'))}-d{match.group('ratio')}-seed{int(match.group('seed'))}" != record["scene_id"]:
                    raise ValueError("instance scene_id is not canonical")
                identity = tuple(record[key] for key in fields[:4])
                if identity in identities:
                    raise ValueError("duplicate_instance_id")
                identities[identity] = (record["source_id"], record["config_id"])
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
                malformed.append({"line": row_number, "error": str(error)})
    return {"sha256": digest.hexdigest(), "identities": identities, "malformed": malformed}


def _instance_coverage(valid: list[dict[str, Any]], instances: str | Path | None) -> dict[str, Any]:
    if instances is None:
        return {"available": False, "coverage_unknown": True,
                "reason": "original_instances_input_not_supplied"}
    expected = load_instance_index(instances)
    observed = {row["_instance_id"]: (row["_source_id"], row["_config_id"]) for row in valid}
    expected_ids = set(expected["identities"])
    observed_ids = set(observed)
    mismatches = sorted(identity for identity in expected_ids & observed_ids
                        if expected["identities"][identity] != observed[identity])
    missing = sorted(expected_ids - observed_ids)
    extra = sorted(observed_ids - expected_ids)
    complete = not expected["malformed"] and not missing and not extra and not mismatches
    return {"available": True, "coverage_unknown": False, "complete": complete,
            "input_sha256": expected["sha256"], "input_instance_count": len(expected_ids),
            "replay_instance_count": len(observed_ids), "missing_instance_ids": missing,
            "extra_instance_ids": extra, "source_or_config_mismatches": mismatches,
            "malformed_input_records": expected["malformed"],
            "valid_input_instance_count": len(expected_ids)}


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    values = list(values)
    return float(np.percentile(values, percentile)) if values else None


def _success(method: dict[str, Any]) -> bool:
    return any(attempt.get("status") == 2 and attempt.get("solve_attempted") and attempt.get("accepted")
               for attempt in method["attempts"])


def _objective(method: dict[str, Any]) -> float | None:
    for attempt in method["attempts"]:
        if _success({"attempts": [attempt]}) and attempt.get("raw_objective") is not None:
            return float(attempt["raw_objective"])
    for attempt in method["attempts"]:
        if _success({"attempts": [attempt]}) and attempt.get("objective") is not None:
            return float(attempt["objective"])
    return None


def _residual_coverage(methods: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return all-attempt and accepted-attempt residual coverage separately."""
    attempts = [attempt for method in methods for attempt in method["attempts"]]
    accepted = [attempt for attempt in attempts
                if attempt["status"] == 2 and attempt["solve_attempted"] and attempt["accepted"]]

    def coverage(checks: list[Any], expected: int) -> dict[str, Any]:
        present = [check for check in checks if check is not None]
        valid = [check for check in present if check["valid"]]
        return {"expected": expected, "checked": len(present), "valid": len(valid),
                "violations": sum(not check["valid"] for check in present),
                "missing": expected - len(present), "complete": expected > 0 and len(present) == expected}

    all_checks = [attempt.get("residuals") for attempt in attempts]
    accepted_checks = [attempt.get("residuals") for attempt in accepted]
    all_qp_checks = [attempt.get("original_residuals") for attempt in attempts if attempt["kind"] == "qp"]
    accepted_qp_checks = [attempt.get("original_residuals") for attempt in accepted if attempt["kind"] == "qp"]
    all_coverage = {
        "attempts": coverage(all_checks, len(attempts)),
        "lifted_original": coverage(all_qp_checks, sum(attempt["kind"] == "qp" for attempt in attempts)),
    }
    accepted_coverage = {
        "attempts": coverage(accepted_checks, len(accepted)),
        "lifted_original": coverage(accepted_qp_checks, sum(attempt["kind"] == "qp" for attempt in accepted)),
    }
    return all_coverage, accepted_coverage


def _method_summary(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    methods = [row["methods"][method] for row in rows]
    attempts = [attempt for value in methods for attempt in value["attempts"]]
    statuses = Counter(str(attempt["status"]) for attempt in attempts)
    all_residual_coverage, accepted_residual_coverage = _residual_coverage(methods)
    latency = [float(value["timing"]["total_seconds"]) * 1000.0 for value in methods]
    raw_objectives = [objective for value in methods if (objective := _objective(value)) is not None]
    fallback = [value for value in methods if value["fallback_used"]]
    return {
        "instance_count": len(rows),
        "successful_instance_count": sum(_success(value) for value in methods),
        "attempt_count": len(attempts),
        "status_counts": dict(sorted(statuses.items())),
        "acceptance": {"accepted_attempts": sum(attempt.get("accepted", False) for attempt in attempts),
                       "successful_instances": sum(_success(value) for value in methods)},
        "residual_coverage": all_residual_coverage["attempts"],
        "lifted_original_residual_coverage": all_residual_coverage["lifted_original"],
        "accepted_residual_coverage": accepted_residual_coverage["attempts"],
        "accepted_lifted_original_residual_coverage": accepted_residual_coverage["lifted_original"],
        "latency_ms": {"p50": _percentile(latency, 50), "p95": _percentile(latency, 95),
                       "p99": _percentile(latency, 99), "frame_count": len(latency),
                       "available": bool(latency)},
        "raw_objective": {"p50": _percentile(raw_objectives, 50),
                          "p95": _percentile(raw_objectives, 95),
                          "p99": _percentile(raw_objectives, 99),
                          "count": len(raw_objectives), "available": bool(raw_objectives)},
        "components_ms": {
            key: sum(float(value["timing"][key]) * 1000.0 for value in methods)
            for key in ("ranking_seconds", "backend_seconds", "prepare_seconds", "adapter_seconds", "fallback_seconds")
        },
        "fallback": {"count": len(fallback), "rate": len(fallback) / len(methods) if methods else None,
                     "accepted_count": sum(_success(value) for value in fallback)},
    }


def paired_bootstrap(values: Iterable[float], seed: int = 0, samples: int = 400) -> dict[str, Any]:
    values = np.asarray(list(values), dtype=float)
    if values.size == 0:
        return {"available": False, "n": 0, "estimate": None, "ci95": None}
    rng = np.random.default_rng(seed)
    estimate = float(np.median(values))
    boot = np.asarray([np.median(values[rng.integers(0, values.size, values.size)]) for _ in range(samples)])
    return {"available": True, "n": int(values.size), "estimate": estimate,
            "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
            "unit": "scene"}


def _scene_latency(rows: list[dict[str, Any]], method: str) -> dict[str, list[float]]:
    result: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        result[row["scene_id"]].append(float(row["methods"][method]["timing"]["total_seconds"]) * 1000.0)
    return result


def _paired_latency(candidate: dict[str, list[float]], baseline: dict[str, list[float]], seed: int,
                    percentile: float) -> dict[str, Any]:
    scenes = sorted(set(candidate) & set(baseline))
    if not scenes:
        return {"available": False, "n": 0, "estimate": None, "ci95": None, "unit": "scene"}
    def statistic(indices: np.ndarray) -> float:
        c = np.concatenate([candidate[scenes[index]] for index in indices])
        b = np.concatenate([baseline[scenes[index]] for index in indices])
        return float(np.percentile(c, percentile) - np.percentile(b, percentile))
    rng = np.random.default_rng(seed)
    indices = np.arange(len(scenes))
    boot = np.asarray([statistic(rng.integers(0, len(scenes), len(scenes))) for _ in range(400)])
    return {"available": True, "n": len(scenes), "estimate": statistic(indices),
            "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
            "unit": "scene", "percentile": percentile}


def _paired(rows: list[dict[str, Any]], method: str, seed: int) -> dict[str, Any]:
    baseline = _scene_latency(rows, "original")
    candidate = _scene_latency(rows, method)
    common = sorted(set(candidate) & set(baseline))
    absolute_gaps: dict[str, list[float]] = defaultdict(list)
    scaled_gaps: dict[str, list[float]] = defaultdict(list)
    paired_instances = 0
    for row in rows:
        original = _objective(row["methods"]["original"])
        current = _objective(row["methods"][method])
        if original is not None and current is not None:
            paired_instances += 1
            absolute_gaps[row["scene_id"]].append(current - original)
            scaled_gaps[row["scene_id"]].append((current - original) / max(1.0, abs(original)))
    absolute_scene_gaps = [float(np.median(absolute_gaps[scene])) for scene in sorted(absolute_gaps)]
    scaled_scene_gaps = [float(np.median(scaled_gaps[scene])) for scene in sorted(scaled_gaps)]
    scaled = paired_bootstrap(scaled_scene_gaps, seed + 200)
    absolute = paired_bootstrap(absolute_scene_gaps, seed + 201)
    objective_gap = {**scaled, "absolute_raw": absolute, "scaled": scaled,
                     "both_success_instance_count": paired_instances,
                     "both_success_scene_count": len(scaled_scene_gaps),
                     "definition": "method_raw_objective-original_raw_objective; scaled divides by max(1,abs(original_raw_objective))",
                     "raw_objective_source": "accepted optimal attempts only"}
    return {
        "common_scene_count": len(common),
        "missing_candidate_scenes": sorted(set(baseline) - set(candidate)),
        "missing_original_scenes": sorted(set(candidate) - set(baseline)),
        "latency_ms": {f"p{percentile}": _paired_latency(candidate, baseline, seed + int(percentile), percentile)
                       for percentile in (50, 95, 99)},
        "objective_gap": objective_gap,
    }


def _group_report(rows: list[dict[str, Any]], environment: str, seed: int) -> dict[str, Any]:
    original_scenes = {row["scene_id"] for row in rows if row["methods"]["original"]["attempts"]}
    methods = {}
    for index, method in enumerate(METHODS):
        summary = _method_summary(rows, method)
        if method != "original":
            summary["paired_to_original"] = _paired(rows, method, seed + index * 100)
        methods[method] = summary
    return {"environment": environment, "scene_count": len({row["scene_id"] for row in rows}),
            "instance_count": len(rows), "original_scene_count": len(original_scenes),
            "methods": methods, "excluded_count": 0,
            "latency_scope": "frozen replay method timings; no full-planner latency gate"}


def make_report(records: Iterable[dict[str, Any]], seed: int = 0,
                instances: str | Path | None = None) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, raw in enumerate(records, 1):
        try:
            row = validate_record(raw, index)
            if row.get("excluded", False):
                exclusions.append(row)
                continue
            if row["_instance_id"] in seen:
                exclusions.append(_excluded(index, "duplicate_instance_id"))
                continue
            seen.add(row["_instance_id"])
            valid.append(row)
        except (ValueError, TypeError) as error:
            exclusions.append(_excluded(index, str(error)))
    environments = {}
    by_count: dict[str, dict[str, Any]] = {"static": {}, "dynamic": {}}
    for environment in ("static", "dynamic"):
        environment_rows = [row for row in valid if row["_environment"] == environment]
        environments[environment] = _group_report(environment_rows, environment, seed)
        for count in sorted({row["_scene_count"] for row in environment_rows}):
            by_count[environment][str(count)] = _group_report(
                [row for row in environment_rows if row["_scene_count"] == count], environment, seed + count)
    return {
        "schema_version": 1,
        "kind": "sando_integer_replay_report",
        "evidence": {"valid_instance_count": len(valid), "excluded_record_count": len(exclusions),
                     "exclusions": exclusions, "duplicate_instance_count": sum("duplicate_instance_id" in row.get("error", "") for row in exclusions),
                     "missing_records_reduce_evidence": True,
                     "instance_coverage": _instance_coverage(valid, instances)},
        "bootstrap": {"seed": seed, "confidence": 0.95, "unit": "scene", "samples": 400},
        "latency_scope": "frozen replay method timings; no full-planner latency gate",
        "environments": environments, "by_num_obstacles": by_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--instances", help="original PlanningInstance JSONL for coverage accounting")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    report = make_report(load_records(args.input), args.seed, args.instances)
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
