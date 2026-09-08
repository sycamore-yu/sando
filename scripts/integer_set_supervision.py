"""Set-valued assignment supervision, near-optimal masks, and geometric labels."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

CONFIG_PATH = Path(__file__).with_name("process_improvement_v1.json")
CONFIG = json.loads(CONFIG_PATH.read_text())
EPS_REL = float(CONFIG["eps_rel"])
J_SCALE = float(CONFIG["j_scale"])
EPS_ABS = float(CONFIG["eps_abs"])
LABEL_TOLERANCE_M = float(CONFIG["label_tolerance_m"])
SET_COST_WEIGHT = float(CONFIG["set_cost_weight"])
WARMUP_EPOCHS = int(CONFIG["warmup_epochs"])
PURPOSE_COMPLETE = "complete_cost_table"
PURPOSE_EXPERT = "expert_demo"
NOT_SOLVED = "not_solved"


def logsumexp(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        raise ValueError("logsumexp requires at least one finite value")
    peak = max(finite)
    return peak + math.log(sum(math.exp(value - peak) for value in finite))


def set_supervision_loss(scores: Sequence[float], good_mask: Sequence[bool],
                         valid_mask: Sequence[bool] | None = None) -> float:
    if len(scores) != len(good_mask):
        raise ValueError("scores and good_mask must have the same length")
    if valid_mask is None:
        valid_mask = [True] * len(scores)
    if len(valid_mask) != len(scores):
        raise ValueError("valid_mask must match scores")
    if not any(valid and good for valid, good in zip(valid_mask, good_mask)):
        raise ValueError("empty good set")
    active = [float(score) for score, valid in zip(scores, valid_mask) if valid]
    good = [float(score) for score, valid, good in zip(scores, valid_mask, good_mask) if valid and good]
    return logsumexp(active) - logsumexp(good)


def set_supervision_loss_torch(scores, good_mask, valid_mask=None):
    import torch
    if valid_mask is None:
        valid_mask = torch.ones_like(scores, dtype=torch.bool)
    good = good_mask & valid_mask
    if not bool(good.any()):
        raise ValueError("empty good set")
    active_logits = scores.masked_fill(~valid_mask, float("-inf"))
    good_logits = scores.masked_fill(~good, float("-inf"))
    return torch.logsumexp(active_logits, dim=-1) - torch.logsumexp(good_logits, dim=-1)


def near_optimal_mask(candidates: Sequence[dict[str, Any]], eps_rel: float = EPS_REL,
                      j_scale: float = J_SCALE, eps_abs: float = EPS_ABS) -> list[bool]:
    feasible = []
    for candidate in candidates:
        if candidate.get("classification") != "feasible":
            continue
        objective = candidate.get("raw_objective")
        if not isinstance(objective, (int, float)) or not math.isfinite(float(objective)):
            raise ValueError("feasible candidate lacks a finite raw objective")
        feasible.append(float(objective))
    if not feasible:
        return [False] * len(candidates)
    reference = min(feasible)
    threshold = eps_rel * max(abs(reference), j_scale) + eps_abs
    mask = []
    for candidate in candidates:
        if candidate.get("classification") != "feasible":
            mask.append(False)
            continue
        mask.append(float(candidate["raw_objective"]) - reference <= threshold)
    return mask


def assignment_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 5:
        raise ValueError("assignment must contain five integers")
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ValueError("assignment must contain five integers")
    return tuple(value)


def evaluate_expression(snapshot: dict[str, Any], values: dict[str, float]) -> float:
    total = float(snapshot.get("constant", 0.0))
    for term in snapshot.get("linear") or []:
        variable = str(term["variable"])
        total += float(term["coefficient"]) * float(values[variable])
    for term in snapshot.get("quadratic") or []:
        left = str(term["left"])
        right = str(term.get("right", left))
        total += float(term["coefficient"]) * float(values[left]) * float(values[right])
    if not math.isfinite(total):
        raise ValueError("expression evaluation is non-finite")
    return total


def recover_numeric_coefficients(instance: dict[str, Any], values: dict[str, float]) -> list[list[float]]:
    axes = instance.get("coefficients")
    if not isinstance(axes, list) or len(axes) != 3:
        raise ValueError("coefficients must contain three axes")
    recovered = []
    for axis in axes:
        if not isinstance(axis, list) or len(axis) != 20:
            raise ValueError("each axis must contain 20 cubic coefficients")
        recovered.append([evaluate_expression(item, values) for item in axis])
    return recovered


def segment_control_points(coefficients: Sequence[Sequence[float]], segment_dt: float) -> list[list[list[float]]]:
    if segment_dt <= 0 or not math.isfinite(segment_dt):
        raise ValueError("segment_dt must be positive")
    points = []
    times = (0.0, segment_dt / 3.0, 2.0 * segment_dt / 3.0, segment_dt)
    for segment in range(5):
        segment_points = []
        for tau in times:
            point = []
            for axis in range(3):
                a, b, c, d = coefficients[axis][segment * 4:segment * 4 + 4]
                point.append(((a * tau + b) * tau + c) * tau + d)
            segment_points.append(point)
        points.append(segment_points)
    return points


def point_in_corridor(point: Sequence[float], planes: Sequence[Sequence[float]], tolerance_m: float) -> bool:
    worst = -math.inf
    for plane in planes:
        if len(plane) != 4:
            raise ValueError("plane must have four numbers")
        normal = math.sqrt(float(plane[0]) ** 2 + float(plane[1]) ** 2 + float(plane[2]) ** 2)
        if not math.isfinite(normal) or normal <= 0:
            raise ValueError("corridor plane normal is invalid")
        violation = (float(plane[0]) * point[0] + float(plane[1]) * point[1] + float(plane[2]) * point[2]
                     - float(plane[3])) / normal
        worst = max(worst, violation)
    return worst <= tolerance_m


def effective_polytope_mask(instance: dict[str, Any], control_points: Sequence[Sequence[Sequence[float]]],
                            tolerance_m: float = LABEL_TOLERANCE_M) -> list[list[bool]]:
    corridors = instance["corridors"]
    valid = instance["valid_mask"]
    mask = []
    for time_index, layer in enumerate(corridors):
        row = []
        for choice, corridor in enumerate(layer):
            if not valid[time_index][choice]:
                row.append(False)
                continue
            planes = corridor.get("planes") if isinstance(corridor, dict) else None
            if not planes:
                row.append(False)
                continue
            row.append(all(point_in_corridor(point, planes, tolerance_m) for point in control_points[time_index]))
        if not any(row):
            raise RuntimeError(f"reference trajectory has no effective polytope at segment {time_index}")
        mask.append(row)
    return mask


def assignments_from_mask(label_mask: Sequence[Sequence[bool]]) -> list[tuple[int, ...]]:
    choices = [[index for index, allowed in enumerate(row) if allowed] for row in label_mask]
    if any(not layer for layer in choices):
        return []
    return [tuple(assignment) for assignment in itertools.product(*choices)]


def good_set_from_trajectories(supports: Sequence[Iterable[tuple[int, ...]]]) -> list[tuple[int, ...]]:
    union: dict[tuple[int, ...], None] = {}
    for support in supports:
        for assignment in support:
            union[tuple(assignment)] = None
    return list(union)


def mixed_segment_counterexample() -> dict[str, Any]:
    """Per-segment mixing of two experts can leave the union of complete assignments."""
    first = ((0, 0, 0, 0, 0),)
    second = ((1, 1, 1, 1, 1),)
    mixed = (0, 1, 0, 1, 0)
    union = set(good_set_from_trajectories([first, second]))
    per_segment = assignments_from_mask([
        [True, True],
        [True, True],
        [True, True],
        [True, True],
        [True, True],
    ])
    return {
        "union": sorted(union),
        "mixed": mixed,
        "mixed_in_union": mixed in union,
        "mixed_in_segment_product": mixed in set(per_segment),
    }


def cartesian_assignments(instance: dict[str, Any]) -> list[tuple[int, ...]]:
    masks = instance.get("valid_mask")
    if not isinstance(masks, list) or len(masks) != 5:
        raise ValueError("valid_mask must contain five layers")
    choices = []
    for row in masks:
        layer = [index for index, allowed in enumerate(row) if allowed]
        if not layer:
            return []
        choices.append(layer)
    return [tuple(item) for item in itertools.product(*choices)]


def expert_demo_record(instance: dict[str, Any], demonstration: dict[str, Any],
                       good_assignments: Sequence[Sequence[int]],
                       sources: dict[str, list[str]] | None = None,
                       tolerance_m: float = LABEL_TOLERANCE_M) -> dict[str, Any]:
    assignments = cartesian_assignments(instance)
    good = [assignment_tuple(item) for item in good_assignments]
    if not good or any(item not in assignments for item in good):
        raise ValueError("good assignments must be a nonempty subset of valid assignments")
    demo_assignment = assignment_tuple(demonstration["assignment"])
    if demo_assignment not in good:
        raise ValueError("demonstration assignment must belong to the good set")
    return {
        "record_purpose": PURPOSE_EXPERT,
        "instance": instance,
        "demonstration": demonstration,
        "good_assignments": [list(item) for item in good],
        "good_assignment_sources": sources or {",".join(map(str, demo_assignment)): ["demonstration"]},
        "label_tolerance_m": tolerance_m,
        "candidates": [
            {
                "assignment": list(assignment),
                "classification": "feasible" if assignment in good else NOT_SOLVED,
                "raw_objective": demonstration.get("raw_objective") if assignment == demo_assignment else None,
                "cost": None,
            }
            for assignment in assignments
        ],
        "costs_complete": False,
    }


def complete_table_record(instance: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_purpose": PURPOSE_COMPLETE,
        "instance": instance,
        "candidates": list(candidates),
        "costs_complete": True,
        "good_assignments": [
            candidate["assignment"] for candidate, keep in zip(candidates, near_optimal_mask(candidates)) if keep
        ],
    }


def geometric_good_set(instance: dict[str, Any], values: dict[str, float],
                       trajectory_id: str = "expert",
                       tolerance_m: float = LABEL_TOLERANCE_M) -> dict[str, Any]:
    coefficients = recover_numeric_coefficients(instance, values)
    points = segment_control_points(coefficients, float(instance["segment_dt"]))
    mask = effective_polytope_mask(instance, points, tolerance_m)
    good = assignments_from_mask(mask)
    return {
        "label_mask": mask,
        "good_assignments": good,
        "trajectory_id": trajectory_id,
        "control_points": points,
    }
