#!/usr/bin/env python3
"""Marked development smoke: 8 train + 4 val synthetic complete tables, seed 0 only."""

from __future__ import annotations

import json
import math
from pathlib import Path

import train_integer_corridor_policy as training
from integer_corridor_policy import valid_assignments
from integer_set_supervision import PURPOSE_COMPLETE


def _instance(seed: int, request: int, split: str) -> dict:
    x = {
        "schema_version": 1, "n": 5, "norm": "Linf", "planner": "SANDO",
        "factor": 1.5, "initial_dt": .1, "dc": .05, "segment_dt": .15,
        "start": [0., 0., 1., .1, .2, .3, .01, .02, .03],
        "goal": [2., 1., 2., .2, .1, .0, .03, .02, .01],
        "map_bounds": [-3., 4., -2., 5., 0., 6.],
        "corridors": [], "valid_mask": [], "assignment_variables": [],
        "scene_id": f"unknown_dynamic-n50-d0.65-seed{seed}",
        "episode_id": f"smoke-{split}-{request}",
        "request_id": str(request), "factor_id": "0",
        "source_id": "dev-smoke", "config_id": "dev-smoke",
        "outcome": {"capture": {"split": split, "capture_round": 0}},
    }
    for t in range(5):
        x["corridors"].append([])
        x["valid_mask"].append([])
        x["assignment_variables"].append([])
        for p in range(2):
            x["corridors"][t].append({"planes": [[1., 0., 0., 4. + 0.01 * request], [0., 1., 0., 4.]]})
            x["valid_mask"][t].append(True)
            x["assignment_variables"][t].append(t * 2 + p + 1)
    return x


def _record(seed: int, request: int, split: str) -> dict:
    instance = _instance(seed, request, split)
    assignments = valid_assignments(instance)
    candidates = []
    for index, assignment in enumerate(assignments):
        feasible = index < 3
        objective = -4.0 + 0.001 * index if feasible else None
        candidates.append({
            "assignment": list(assignment),
            "classification": "feasible" if feasible else "infeasible",
            "raw_objective": objective,
            "cost": 0.0,
        })
    minimum = -4.0
    maximum = -4.0 + 0.002
    scale = max(maximum - minimum, 1e-6 * max(1.0, abs(minimum), abs(maximum)))
    for candidate in candidates:
        if candidate["classification"] == "feasible":
            candidate["cost"] = (float(candidate["raw_objective"]) - minimum) / scale
        else:
            candidate["cost"] = 2.0
    return {"instance": instance, "costs_complete": True, "record_purpose": PURPOSE_COMPLETE,
            "candidates": candidates}


def main() -> int:
    train_records = [training._parse_record(_record(0, i, "train")) for i in range(8)]
    validation_records = [training._parse_record(_record(100, i, "validation")) for i in range(4)]
    if any(item is None for item in train_records + validation_records):
        raise SystemExit("smoke records failed validation")
    _, metadata, progress = training.train(
        train_records, validation_records, method="set", seed=0, epochs=30, batch_size=4)
    first = progress[0]["loss"]
    last = progress[-1]["loss"]
    report = {
        "marked": "development_small_batch",
        "method": "set",
        "seed": 0,
        "n_train": len(train_records),
        "n_validation": len(validation_records),
        "first_loss": first,
        "last_loss": last,
        "best_epoch": metadata["best_epoch"],
        "best_validation_metric": min(item["validation_metric"] for item in progress),
        "loss_decreased": last < first,
    }
    out = Path("/root/sando_ws/dev-results/set_loss_smoke.json")
    if not out.parent.exists():
        out = Path("docker/dev-workspace/results/set_loss_smoke.json")
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if not math.isfinite(last):
        raise SystemExit("set-loss smoke did not produce a finite loss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
