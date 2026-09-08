#!/usr/bin/env python3
"""Train the small corridor policy from labelled JSONL instances."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import torch
import torch.nn.functional as F

from integer_corridor_policy import FEATURE_SPEC, CorridorPolicy, valid_assignments
from integer_corridor_training_batch import batched_scores, prepare_records
from integer_set_supervision import (
    PURPOSE_COMPLETE,
    PURPOSE_EXPERT,
    SET_COST_WEIGHT,
    WARMUP_EPOCHS,
    assignment_tuple,
    near_optimal_mask,
    set_supervision_loss_torch,
)

_INSTANCE_KEYS = ("schema_version", "n", "norm", "planner", "scene_id", "episode_id", "request_id", "factor_id", "source_id", "config_id", "factor", "initial_dt", "dc", "segment_dt", "planning_start_time", "observation_time", "t0", "start", "goal", "map_bounds", "corridors", "valid_mask", "assignment_variables", "outcome")


def _instance(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("instance")
    if not isinstance(value, dict):
        raise ValueError("label record must contain an instance object")
    return value


def _split(instance: dict[str, Any]) -> tuple[Any, Any]:
    capture = instance.get("outcome", {}).get("capture", {})
    if not isinstance(capture, dict):
        capture = {}
    return capture.get("split"), capture.get("capture_round")


def _check_identity(instance: dict[str, Any], validation: bool) -> None:
    ids = ("scene_id", "episode_id", "request_id", "factor_id", "source_id", "config_id")
    if any(not isinstance(instance.get(key), str) or not instance[key] for key in ids):
        raise ValueError("instance identifiers must be nonempty")
    split, capture_round = _split(instance)
    if split not in (("validation",) if validation else ("train",)):
        raise ValueError("record split does not match its input file")
    if validation and capture_round != 0:
        raise ValueError("validation data must be capture round zero")
    if not validation and capture_round not in (0, 1, 2):
        raise ValueError("training data must be capture round zero, one, or two")
    match = re.search(r"(?:^|[-_:])seed(\d+)(?:$|[-_:])", instance["scene_id"])
    if not match:
        raise ValueError("scene_id must contain a numeric seed")
    seed = int(match.group(1))
    if (split == "train" and not 0 <= seed <= 39) or (split == "validation" and not 100 <= seed <= 109):
        raise ValueError("scene seed is outside its locked split range")


def _slim_instance(instance: dict[str, Any]) -> dict[str, Any]:
    return {key: instance[key] for key in _INSTANCE_KEYS}


def _assignment(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != 5 or any(not isinstance(x, int) or isinstance(x, bool) for x in value):
        raise ValueError("candidate assignment must contain five integers")
    return tuple(value)


def _validated_record(record: dict[str, Any]) -> dict[str, Any] | None:
    instance = _instance(record)
    expected = valid_assignments(instance)
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or not record.get("costs_complete", False) or not expected:
        return None
    by_assignment: dict[tuple[int, ...], dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        assignment = _assignment(candidate.get("assignment"))
        if assignment in by_assignment:
            raise ValueError("duplicate candidate assignment")
        if assignment not in expected:
            raise ValueError("candidate assignment is not a valid Cartesian assignment")
        by_assignment[assignment] = candidate
    if set(by_assignment) != set(expected) or len(by_assignment) != len(expected):
        raise ValueError("candidate assignments are partial or misaligned")
    ordered = [by_assignment[assignment] for assignment in expected]
    feasible = [candidate for candidate in ordered if candidate.get("classification") == "feasible"]
    if not feasible or any(candidate.get("classification") not in ("feasible", "infeasible") for candidate in ordered):
        return None
    objectives = []
    for candidate in feasible:
        objective = candidate.get("raw_objective")
        if not isinstance(objective, (int, float)) or not math.isfinite(float(objective)):
            raise ValueError("feasible candidate lacks a finite raw objective")
        objectives.append(float(objective))
    minimum, maximum = min(objectives), max(objectives)
    scale = max(maximum - minimum, 1e-6 * max(1.0, abs(minimum), abs(maximum)))
    for candidate in ordered:
        cost = candidate.get("cost")
        if not isinstance(cost, (int, float)) or not math.isfinite(float(cost)):
            raise ValueError("candidate lacks a finite cost")
        expected_cost = 2.0 if candidate.get("classification") == "infeasible" else (float(candidate["raw_objective"]) - minimum) / scale
        if abs(float(cost) - expected_cost) > 2e-6 or (candidate.get("classification") == "feasible" and not 0.0 <= float(cost) <= 1.0 + 2e-6):
            raise ValueError("candidate cost does not match the recorded objective")
    minimum_cost = min(float(candidate["cost"]) for candidate in feasible)
    best = min(assignment for assignment, candidate in zip(expected, ordered)
               if candidate.get("classification") == "feasible"
               and float(candidate["cost"]) <= minimum_cost + 2e-6)
    good = [bool(flag) for flag in near_optimal_mask(ordered)]
    return {"instance": instance, "assignments": expected, "candidates": ordered,
            "best": expected.index(best), "good_mask": good, "record_purpose": PURPOSE_COMPLETE,
            "costs_complete": True}


def _validated_expert_record(record: dict[str, Any]) -> dict[str, Any] | None:
    instance = _instance(record)
    expected = valid_assignments(instance)
    if not expected:
        return None
    good = [assignment_tuple(item) for item in record.get("good_assignments") or []]
    if not good or any(item not in expected for item in good):
        return None
    demonstration = record.get("demonstration")
    if not isinstance(demonstration, dict):
        raise ValueError("expert demo requires a demonstration object")
    demo_assignment = assignment_tuple(demonstration.get("assignment"))
    if demo_assignment not in good:
        raise ValueError("demonstration assignment is not in the good set")
    return {
        "instance": instance,
        "assignments": expected,
        "candidates": [{"assignment": list(item), "classification": "not_solved", "raw_objective": None, "cost": None}
                       for item in expected],
        "best": expected.index(demo_assignment),
        "good_mask": [item in set(good) for item in expected],
        "record_purpose": PURPOSE_EXPERT,
        "costs_complete": False,
    }


def _parse_record(record: dict[str, Any]) -> dict[str, Any] | None:
    purpose = record.get("record_purpose")
    if purpose == PURPOSE_EXPERT or (purpose is None and record.get("costs_complete") is not True
                                     and record.get("good_assignments")):
        return _validated_expert_record(record)
    return _validated_record(record)


def load_labelled(path: str | Path, validation: bool = False, statistics=None) -> list[dict[str, Any]]:
    paths: Sequence[str | Path] = [path] if isinstance(path, (str, Path)) else path
    result = []
    seen = set()
    statistics = statistics if statistics is not None else {}
    statistics.update(total=0, complete=0, excluded={})
    for path_item in paths:
        with Path(path_item).open() as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"{path_item}:{line_number}: record must be an object")
                instance = _instance(record)
                _check_identity(instance, validation)
                key = tuple(instance[name] for name in ("scene_id", "episode_id", "request_id", "factor_id"))
                if key in seen:
                    raise ValueError(f"duplicate planning instance in training inputs: {key}")
                seen.add(key)
                statistics["total"] += 1
                parsed = _parse_record(record)
                if parsed is not None:
                    parsed["instance"] = _slim_instance(parsed["instance"])
                    parsed["candidates"] = [{key: candidate[key] for key in ("assignment", "classification", "raw_objective", "cost")} for candidate in parsed["candidates"]]
                    result.append(parsed)
                    statistics["complete"] += 1
                else:
                    reason = record.get("excluded_reason", "incomplete_costs")
                    statistics["excluded"][reason] = statistics["excluded"].get(reason, 0) + 1
    return result


def check_split_disjoint(train: list[dict[str, Any]], validation: list[dict[str, Any]]) -> None:
    train_scenes = {item["instance"].get("scene_id") for item in train}
    validation_scenes = {item["instance"].get("scene_id") for item in validation}
    overlap = train_scenes & validation_scenes
    if overlap:
        raise ValueError("training and validation scenes overlap")


def _costs(record: dict[str, Any]) -> torch.Tensor:
    return torch.tensor([2.0 if item.get("classification") == "infeasible" else float(item["cost"]) for item in record["candidates"]], dtype=torch.float64)


def _scores(policy: CorridorPolicy, record: dict[str, Any]) -> torch.Tensor:
    assignments, scores = policy.score_all(record["instance"])
    if assignments != record["assignments"]:
        raise ValueError("policy assignment ordering differs from labels")
    return scores


@torch.no_grad()
def validation_metric(policy: CorridorPolicy, records: list[dict[str, Any]]) -> float:
    if not records:
        return float("inf")
    values = []
    for record in records:
        scores = _scores(policy, record).detach().tolist()
        ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], record["assignments"][index]))
        value = 2.0
        for index in ranked[:3]:
            if record["candidates"][index].get("classification") == "feasible":
                value = float(record["candidates"][index]["cost"])
                break
        values.append(value)
    return float(np.mean(values))


@torch.no_grad()
def validation_metric_batched(policy: CorridorPolicy, records: list[dict[str, Any]], prepared=None) -> float:
    """Compute the reference metric from one batched score pass per epoch."""
    if not records:
        return float("inf")
    prepared = prepare_records(records) if prepared is None else prepared
    if len(prepared) != len(records):
        raise ValueError("prepared validation records do not match inputs")
    values = []
    for offset in range(0, len(records), 32):
        scores_batch = batched_scores(policy, prepared[offset:offset + 32])
        for record, scores in zip(records[offset:offset + 32], scores_batch):
            scores = scores.detach().tolist()
            ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], record["assignments"][index]))
            value = 2.0
            for index in ranked[:3]:
                if record["candidates"][index].get("classification") == "feasible":
                    value = float(record["candidates"][index]["cost"])
                    break
            values.append(value)
    return float(np.mean(values))


def _set_loss(scores: torch.Tensor, record: dict[str, Any]) -> torch.Tensor:
    mask = torch.tensor(record["good_mask"], dtype=torch.bool)
    return set_supervision_loss_torch(scores, mask)


def train(train_records: list[dict[str, Any]], validation_records: list[dict[str, Any]], method: str, seed: int, epochs: int = 100, batch_size: int = 32, callback: Callable[[CorridorPolicy, dict[str, torch.Tensor], dict[str, Any]], None] | None = None) -> tuple[CorridorPolicy, dict[str, Any], list[dict[str, Any]]]:
    if method not in ("bc", "cost", "set"):
        raise ValueError("method must be bc, cost, or set")
    if seed not in (0, 1, 2):
        raise ValueError("seed must be 0, 1, or 2")
    if not train_records or not validation_records:
        raise ValueError("training and validation require at least one usable record")
    if method == "cost" and any(not record.get("costs_complete") for record in train_records + validation_records):
        raise ValueError("cost training requires complete cost tables")
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    policy = CorridorPolicy()
    optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)
    prepared_train = prepare_records(train_records)
    prepared_validation = prepare_records(validation_records)
    best_metric, best_epoch, best_state = float("inf"), 0, None
    progress = []
    for epoch in range(1, epochs + 1):
        policy.train()
        order = list(range(len(train_records))); random.Random(seed + epoch).shuffle(order)
        losses = []
        for offset in range(0, len(order), batch_size):
            optimizer.zero_grad()
            batch_indices = order[offset:offset + batch_size]
            batch = [train_records[index] for index in batch_indices]
            logits = batched_scores(policy, [prepared_train[index] for index in batch_indices])
            ce_loss = torch.stack([F.cross_entropy(scores.reshape(1, -1), torch.tensor([record["best"]])) for scores, record in zip(logits, batch)]).mean()
            set_loss = torch.stack([_set_loss(scores, record) for scores, record in zip(logits, batch)]).mean()
            loss = ce_loss
            if method == "set":
                loss = set_loss
            if method == "cost" and epoch > WARMUP_EPOCHS:
                expected_cost = torch.stack([torch.softmax(scores, dim=0).dot(_costs(record)) for scores, record in zip(logits, batch)]).mean()
                loss = expected_cost + SET_COST_WEIGHT * ce_loss
            if method == "set" and epoch > WARMUP_EPOCHS and all(record.get("costs_complete") for record in batch):
                expected_cost = torch.stack([torch.softmax(scores, dim=0).dot(_costs(record)) for scores, record in zip(logits, batch)]).mean()
                loss = expected_cost + SET_COST_WEIGHT * set_loss
            loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
        policy.eval()
        metric = validation_metric_batched(policy, validation_records, prepared_validation)
        improved = metric < best_metric
        if improved:
            best_metric, best_epoch = metric, epoch
            best_state = {name: value.detach().clone() for name, value in policy.state_dict().items()}
        epoch_metrics = {"epoch": epoch, "loss": float(np.mean(losses)), "validation_metric": metric, "best_epoch": best_epoch, "improved": improved}
        progress.append(epoch_metrics)
        if callback is not None:
            callback(policy, best_state, epoch_metrics)
    if best_state is None:
        raise RuntimeError("training did not produce a checkpoint")
    policy.load_state_dict(best_state)
    metadata = {"best_epoch": best_epoch, "method": method, "seed": seed, "epochs": epochs, "batch_size": batch_size, "learning_rate": 1e-3,
                "batch_backend": "ragged_plane_and_candidate_v1"}
    return policy, metadata, progress


def _data_hash(paths: list[str | Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", nargs="+", required=True)
    parser.add_argument("--validation", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--method", choices=("bc", "cost", "set"), default="bc")
    parser.add_argument("--seed", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.threads <= 0:
        parser.error("--threads must be positive")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    output = Path(args.output)
    output.mkdir(parents=False, exist_ok=False)
    train_statistics, validation_statistics = {}, {}
    train_records = load_labelled(args.train, statistics=train_statistics)
    validation_records = load_labelled(args.validation, validation=True, statistics=validation_statistics)
    check_split_disjoint(train_records, validation_records)
    base_metadata = {"method": args.method, "seed": args.seed, "epochs": 100, "batch_size": 32, "learning_rate": 1e-3, "data_hash": _data_hash(args.train + args.validation), "train_scenes": sorted({item["instance"]["scene_id"] for item in train_records}), "validation_scenes": sorted({item["instance"]["scene_id"] for item in validation_records}), "torch_version": torch.__version__, "feature_spec": FEATURE_SPEC,
                     "batch_backend": "ragged_plane_and_candidate_v1", "batch_backend_version": 1,
                     "training_script_sha256": _file_hash(Path(__file__)),
                     "training_batch_sha256": _file_hash(Path(__file__).with_name("integer_corridor_training_batch.py")),
                     "policy_source_sha256": _file_hash(Path(__file__).with_name("integer_corridor_policy.py"))}
    base_metadata.update(threads=args.threads, interop_threads=1, device="cpu", dtype="float64",
                         bc_tie_tolerance=2e-6, bc_tie_units="normalized_cost",
                         train_coverage=train_statistics, validation_coverage=validation_statistics)
    progress_stream = (output / "progress.jsonl").open("x")
    def checkpoint(policy, best_state, metrics):
        progress_stream.write(json.dumps(metrics, allow_nan=False) + "\n"); progress_stream.flush()
        print(json.dumps(metrics, allow_nan=False), flush=True)
        if metrics["improved"]:
            policy.load_state_dict(best_state)
            (output / "model.json").write_text(json.dumps(policy.to_json({**base_metadata, "best_epoch": metrics["best_epoch"]}), allow_nan=False, separators=(",", ":")) + "\n")
    policy, metadata, progress = train(train_records, validation_records, args.method, args.seed, callback=checkpoint)
    progress_stream.close()
    (output / "completed.json").write_text(json.dumps({**base_metadata, **metadata,
        "completed_epochs": len(progress), "best_validation_metric": min(
            item["validation_metric"] for item in progress)}, allow_nan=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
