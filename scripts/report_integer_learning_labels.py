#!/usr/bin/env python3
"""Summarize exhaustive integer-planning labels without reinterpreting timing.

The labeler writes one JSON object per planning instance.  This report counts
the recorded candidate classifications and uses only ``timing.wall_seconds``
for labeling-time statistics; backend and attempt timings are reported
separately.  A malformed row is an error rather than a silently excluded
instance.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


CLASSIFICATIONS = ("feasible", "infeasible", "unknown")
EXCLUSION_REASONS = ("all_infeasible", "unknown_or_infeasible_results", "no_valid_assignments")


def _finite_number(value: Any, name: str, *, nonnegative: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if nonnegative and result < 0:
        raise ValueError(f"{name} must be nonnegative")
    return result


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _optional_number(value: Any, name: str, *, nonnegative: bool = False) -> None:
    if value is not None:
        _finite_number(value, name, nonnegative=nonnegative)


def _validate_attempt(attempt: Any, row_number: int, candidate_number: int, attempt_number: int) -> None:
    prefix = f"row {row_number} candidate {candidate_number} attempt {attempt_number}"
    if not isinstance(attempt, dict):
        raise ValueError(f"{prefix} must be an object")
    if isinstance(attempt.get("status"), bool) or not isinstance(attempt.get("status"), int):
        raise ValueError(f"{prefix}.status must be an integer")
    _finite_number(attempt.get("wall_time"), f"{prefix}.wall_time")
    _optional_number(attempt.get("backend_time"), f"{prefix}.backend_time")
    _optional_number(attempt.get("objective"), f"{prefix}.objective")
    residuals = attempt.get("residuals")
    if not isinstance(residuals, dict) or not isinstance(residuals.get("valid"), bool):
        raise ValueError(f"{prefix}.residuals.valid must be boolean")


def validate_label(row: Any, row_number: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError(f"row {row_number} must be an object")
    if isinstance(row.get("schema_version"), bool) or row.get("schema_version") != 1:
        raise ValueError(f"row {row_number}.schema_version must be 1")
    instance = row.get("instance")
    if not isinstance(instance, dict):
        raise ValueError(f"row {row_number}.instance must be an object")
    for key in ("scene_id", "episode_id", "request_id", "factor_id"):
        if not isinstance(instance.get(key), str) or not instance[key]:
            raise ValueError(f"row {row_number}.instance.{key} must be a nonempty string")
    n = instance.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError(f"row {row_number}.instance.n must be a nonnegative integer")
    valid_mask = instance.get("valid_mask")
    if not isinstance(valid_mask, list) or len(valid_mask) != n:
        raise ValueError(f"row {row_number}.instance.valid_mask must have n layers")
    valid_choices = []
    for layer_number, layer in enumerate(valid_mask):
        if not isinstance(layer, list) or any(not isinstance(value, bool) for value in layer):
            raise ValueError(f"row {row_number}.instance.valid_mask[{layer_number}] must be a boolean array")
        valid_choices.append([index for index, value in enumerate(layer) if value])
    if math.prod(map(len, valid_choices)) > 243:
        raise ValueError(f"row {row_number}.instance.valid_mask defines more than 243 assignments")
    expected_assignments = set(itertools.product(*valid_choices)) if valid_choices and all(valid_choices) else set()

    candidates = row.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError(f"row {row_number}.candidates must be an array")
    total = _count(row.get("total_valid_assignments"), f"row {row_number}.total_valid_assignments")
    if total > 243:
        raise ValueError(f"row {row_number}.total_valid_assignments exceeds 243")
    if total != len(candidates):
        raise ValueError(f"row {row_number}.total_valid_assignments disagrees with candidates")
    classifications = Counter()
    seen_assignments = set()
    attempt_count = retries = 0
    for candidate_number, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            raise ValueError(f"row {row_number} candidate {candidate_number} must be an object")
        classification = candidate.get("classification")
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"row {row_number} candidate {candidate_number}.classification is invalid")
        classifications[classification] += 1
        assignment = candidate.get("assignment")
        if not isinstance(assignment, list) or any(isinstance(value, bool) or not isinstance(value, int) for value in assignment):
            raise ValueError(f"row {row_number} candidate {candidate_number}.assignment must be an integer array")
        if len(assignment) != n or tuple(assignment) not in expected_assignments:
            raise ValueError(f"row {row_number} candidate {candidate_number}.assignment is not a valid full assignment")
        if tuple(assignment) in seen_assignments:
            raise ValueError(f"row {row_number} candidate {candidate_number}.assignment is duplicated")
        seen_assignments.add(tuple(assignment))
        _optional_number(candidate.get("raw_objective"), f"row {row_number} candidate {candidate_number}.raw_objective")
        _optional_number(candidate.get("cost"), f"row {row_number} candidate {candidate_number}.cost", nonnegative=True)
        attempts = candidate.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ValueError(f"row {row_number} candidate {candidate_number}.attempts must be nonempty")
        attempt_count += len(attempts)
        retries += len(attempts) > 1
        for attempt_number, attempt in enumerate(attempts, 1):
            _validate_attempt(attempt, row_number, candidate_number, attempt_number)
    if seen_assignments != expected_assignments:
        raise ValueError(f"row {row_number}.candidates do not cover the full valid assignment Cartesian product")

    failurestats = row.get("failurestats")
    if not isinstance(failurestats, dict):
        raise ValueError(f"row {row_number}.failurestats must be an object")
    if _count(failurestats.get("unknown"), f"row {row_number}.failurestats.unknown") != classifications["unknown"]:
        raise ValueError(f"row {row_number}.failurestats.unknown disagrees with candidates")
    if _count(failurestats.get("proven_infeasible"), f"row {row_number}.failurestats.proven_infeasible") != classifications["infeasible"]:
        raise ValueError(f"row {row_number}.failurestats.proven_infeasible disagrees with candidates")
    all_infeasible = failurestats.get("all_infeasible")
    expected_all_infeasible = bool(candidates) and classifications["infeasible"] == len(candidates)
    if not isinstance(all_infeasible, bool) or all_infeasible != expected_all_infeasible:
        raise ValueError(f"row {row_number}.failurestats.all_infeasible disagrees with candidates")

    timing = row.get("timing")
    if not isinstance(timing, dict):
        raise ValueError(f"row {row_number}.timing must be an object")
    for key in ("covered", "excluded", "attempt_count", "retries"):
        _count(timing.get(key), f"row {row_number}.timing.{key}")
    if timing["attempt_count"] != attempt_count or timing["retries"] != retries:
        raise ValueError(f"row {row_number}.timing attempt counts disagree with candidates")
    for key in ("wall_seconds", "solve_and_residual_wall_seconds", "model_conversion_seconds"):
        _finite_number(timing.get(key), f"row {row_number}.timing.{key}")
    # A finite negative backend runtime is producer evidence of a numeric
    # solver error; preserve the unknown label and flag the timing below.
    _finite_number(timing.get("backend_seconds"), f"row {row_number}.timing.backend_seconds", nonnegative=False)

    complete = row.get("costs_complete")
    if not isinstance(complete, bool):
        raise ValueError(f"row {row_number}.costs_complete must be boolean")
    expected_complete = classifications["unknown"] == 0 and classifications["feasible"] > 0
    if complete != expected_complete:
        raise ValueError(f"row {row_number}.costs_complete disagrees with candidate classifications")
    reason = row.get("excluded_reason")
    if reason is not None and (not isinstance(reason, str) or reason not in EXCLUSION_REASONS):
        raise ValueError(f"row {row_number}.excluded_reason is invalid")
    if complete and reason is not None:
        raise ValueError(f"row {row_number} complete labels cannot have an exclusion reason")
    if not complete and reason is None:
        raise ValueError(f"row {row_number} incomplete labels require excluded_reason")
    if timing["covered"] != (total if complete else 0) or timing["excluded"] != (0 if complete else total):
        raise ValueError(f"row {row_number}.timing covered/excluded disagrees with costs_complete")
    if complete and not classifications["feasible"]:
        raise ValueError(f"row {row_number} complete labels require a feasible candidate")
    if all_infeasible and reason != "all_infeasible":
        raise ValueError(f"row {row_number} all-infeasible labels require the all_infeasible reason")
    if reason == "all_infeasible" and not all_infeasible:
        raise ValueError(f"row {row_number} all_infeasible reason requires all candidates to be infeasible")
    if reason == "no_valid_assignments" and total:
        raise ValueError(f"row {row_number} no_valid_assignments reason requires no candidates")
    if reason == "unknown_or_infeasible_results" and not classifications["unknown"]:
        raise ValueError(f"row {row_number} unknown_or_infeasible_results requires an unknown candidate")
    return row


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(position)); upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def make_report(rows: Iterable[dict[str, Any]], expected_instances: int | None = None) -> dict[str, Any]:
    rows = list(rows)
    actual = len(rows)
    classification_totals = Counter()
    exclusion_totals = Counter()
    wall_seconds: list[float] = []
    solve_seconds: list[float] = []
    backend_seconds: list[float] = []
    conversion_seconds: list[float] = []
    attempts = retries = 0
    invalid_backend_timing = 0
    complete = all_infeasible = unknown = usable = 0
    for row in rows:
        candidates = row["candidates"]
        for candidate in candidates:
            classification_totals[candidate["classification"]] += 1
        timing = row["timing"]
        wall_seconds.append(float(timing["wall_seconds"]))
        solve_seconds.append(float(timing["solve_and_residual_wall_seconds"]))
        backend_seconds.append(float(timing["backend_seconds"]))
        invalid_backend_timing += sum(
            isinstance(attempt.get("backend_time"), (int, float)) and not isinstance(attempt.get("backend_time"), bool)
            and float(attempt["backend_time"]) < 0 for candidate in candidates for attempt in candidate["attempts"]
        )
        conversion_seconds.append(float(timing["model_conversion_seconds"]))
        attempts += timing["attempt_count"]
        retries += timing["retries"]
        complete += row["costs_complete"]
        all_infeasible += row["failurestats"]["all_infeasible"]
        unknown += bool(row["failurestats"]["unknown"])
        usable += row["costs_complete"]
        if row.get("excluded_reason") is not None:
            exclusion_totals[row["excluded_reason"]] += 1
    result = {
        "schema_version": 1,
        "actual_instances": actual,
        "expected_instances": expected_instances,
        "complete_instances": complete,
        "all_infeasible_instances": all_infeasible,
        "unknown_instances": unknown,
        "excluded_instances": actual - usable,
        "usable_instances": usable,
        "usable_fraction": usable / actual if actual else None,
        "incomplete": expected_instances is not None and actual != expected_instances,
        "exclusion_reasons": dict(sorted(exclusion_totals.items())),
        "candidate_counts": {
            "total": sum(classification_totals.values()),
            "feasible": classification_totals["feasible"],
            "infeasible": classification_totals["infeasible"],
            "proven_infeasible": classification_totals["infeasible"],
            "unknown": classification_totals["unknown"],
        },
        "retries": {"attempts": attempts, "candidate_retries": retries, "instances_with_retries": sum(row["timing"]["retries"] > 0 for row in rows)},
        "wall_labeling_seconds": {
            "total": sum(wall_seconds),
            "p50": _percentile(wall_seconds, 50),
            "p95": _percentile(wall_seconds, 95),
            "p99": _percentile(wall_seconds, 99),
            "instance_count": actual,
            "definition": "recorded timing.wall_seconds per labeled instance",
        },
        "recorded_timing_seconds": {
            "solve_and_residual_total": sum(solve_seconds),
            "backend_total": None if invalid_backend_timing or any(value < 0 for value in backend_seconds) else sum(backend_seconds),
            "backend_total_raw": sum(backend_seconds),
            "model_conversion_total": sum(conversion_seconds),
        },
        "invalid_backend_timing_attempts": invalid_backend_timing,
    }
    result["candidate_outcomes"] = dict(result["candidate_counts"])
    result["candidate_retries"] = retries
    return result


def load_labels(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows = []
    seen_instances = set()
    row_number = 0
    for path_value in paths:
        path = Path(path_value)
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                row_number += 1
                try:
                    value = json.loads(line)
                    validated = validate_label(value, row_number)
                    identity = tuple(validated["instance"][key] for key in ("scene_id", "episode_id", "request_id", "factor_id"))
                    if identity in seen_instances:
                        raise ValueError(f"row {row_number} duplicates instance identity")
                    seen_instances.add(identity)
                    rows.append(validated)
                except (json.JSONDecodeError, ValueError) as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-instances", type=int)
    args = parser.parse_args()
    if args.expected_instances is not None and args.expected_instances < 0:
        parser.error("--expected-instances must be nonnegative")
    try:
        rows = load_labels(args.input)
        report = make_report(rows, args.expected_instances)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError) as error:
        print(f"report_integer_learning_labels: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
