#!/usr/bin/env python3
"""Select 12 captured requests and query the joint-time factor grid.

Reads the learning-stages-v2 snapshot copy (read-only) and writes only
under docker/dev-workspace/results/joint-time-v2/small-table/.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from reconstructable_request import (
    FACTOR_REL_TOL,
    from_planning_instance,
    missing_observation_fields,
    query,
    time_query,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "docker/dev-workspace/results/learning-stages-v2/snapshot"
DEFAULT_CONFIG = ROOT / "docker/dev-workspace/results/joint-time-v2/config.json"
DEFAULT_OUTPUT = ROOT / "docker/dev-workspace/results/joint-time-v2/small-table"

CLASSES = (
    {
        "class_id": "unknown_dynamic-n50",
        "family": "unknown_dynamic",
        "run_prefix": "unknown_dynamic-n50-d0.65",
        "difficulty": "easy",
    },
    {
        "class_id": "unknown_dynamic-n100",
        "family": "unknown_dynamic",
        "run_prefix": "unknown_dynamic-n100-d0.65",
        "difficulty": "medium",
    },
    {
        "class_id": "unknown_dynamic-n200",
        "family": "unknown_dynamic",
        "run_prefix": "unknown_dynamic-n200-d0.65",
        "difficulty": "hard",
    },
    {
        "class_id": "static_forest-easy",
        "family": "static_forest",
        "run_prefix": "static_forest-easy",
        "difficulty": "easy",
    },
    {
        "class_id": "static_forest-medium",
        "family": "static_forest",
        "run_prefix": "static_forest-medium",
        "difficulty": "medium",
    },
    {
        "class_id": "static_forest-hard",
        "family": "static_forest",
        "run_prefix": "static_forest-hard",
        "difficulty": "hard",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot_root = args.snapshot.resolve()
    config = json.loads(args.config.read_text())
    selected = select_requests(snapshot_root)
    if len(selected) != 12:
        raise SystemExit(f"expected 12 requests, selected {len(selected)}")

    query_factors_template = list(config.get("query_grid") or [])
    off_grid = list(config.get("off_grid") or [1.37])
    output = args.output.resolve()
    requests_dir = output / "requests"
    if requests_dir.exists():
        for path in requests_dir.glob("*.json"):
            path.unlink()
    requests_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    classifications = Counter()
    missing_union: set[str] = set()
    per_request_missing = []
    for item in selected:
        snapshot = from_planning_instance(item["instance"], item["sidecars"])
        snapshot["class_id"] = item["class_id"]
        snapshot["same_map_across_seeds"] = item["family"] == "static_forest"
        snapshot["source"] = {
            "split": item["split"],
            "seed": item["seed"],
            "run_dir": item["run_rel"],
            "instances_jsonl": item["instances_rel"],
            "line_index": item["line_index"],
            "factor_id": item["instance"].get("factor_id"),
        }
        filename = f"{item['class_id']}__{item['scene_id']}__request-{item['request_id']}.json"
        (requests_dir / filename).write_text(
            json.dumps(snapshot, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        original_factor = snapshot["time_inputs"]["original_factor"]
        factors = unique_factors(query_factors_template + [original_factor] + off_grid)
        factor_records = []
        for factor in factors:
            record = query(snapshot, factor, original_instance=item["instance"])
            classifications[record["classification"]] += 1
            factor_records.append(record)
        missing = missing_observation_fields(snapshot)
        missing_union.update(missing)
        per_request_missing.append(
            {
                "class_id": item["class_id"],
                "scene_id": item["scene_id"],
                "request_id": item["request_id"],
                "snapshot_file": f"requests/{filename}",
                "missing_fields": missing,
            }
        )
        identity = dict(snapshot["identity"])
        rows.append(
            {
                "class_id": item["class_id"],
                "identity": identity,
                "same_map_across_seeds": item["family"] == "static_forest",
                "original_factor": original_factor,
                "original_segment_dt": snapshot["time_inputs"]["original_segment_dt"],
                "snapshot_file": f"requests/{filename}",
                "source": snapshot["source"],
                "factors": factor_records,
            }
        )

    table = {
        "schema_version": 1,
        "kind": "sando_joint_time_small_table",
        "source_commit": config.get("source_commit"),
        "adr": config.get("adr"),
        "snapshot_root": str(snapshot_root.relative_to(ROOT)) if snapshot_root.is_relative_to(ROOT) else str(snapshot_root),
        "query_grid": query_factors_template,
        "off_grid": off_grid,
        "residual_tolerance": config.get("residual_tolerance", FACTOR_REL_TOL),
        "counts": {
            "requests": len(rows),
            "same_factor_reference": int(classifications.get("same_factor_reference", 0)),
            "blocked_missing_observation": int(classifications.get("blocked_missing_observation", 0)),
        },
        "rows": rows,
    }
    missing_payload = {
        "schema_version": 1,
        "kind": "sando_joint_time_missing_fields",
        "union": sorted(missing_union),
        "per_request": per_request_missing,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "table.json").write_text(json.dumps(table, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (output / "missing_fields.json").write_text(
        json.dumps(missing_payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (output / "README.md").write_text(readme_text(table, missing_payload, snapshot_root))
    _validate_table(table, selected)
    print(json.dumps({"wrote": str(output / "table.json"), "identities": [
        {
            "class_id": row["class_id"],
            "scene_id": row["identity"]["scene_id"],
            "request_id": row["identity"]["request_id"],
            "original_factor": row["original_factor"],
        }
        for row in rows
    ], "missing_union": missing_payload["union"], "counts": table["counts"]}, indent=2, sort_keys=True))
    return 0


def select_requests(snapshot_root: Path) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for spec in CLASSES:
        found = []
        for split in ("train", "validation"):
            for seed in _seeds(snapshot_root / split):
                run_name = f"{spec['run_prefix']}-seed{seed}"
                run_dir = snapshot_root / split / f"seed{seed}" / "runs" / run_name
                instances_path = run_dir / "instances.jsonl"
                if not instances_path.is_file():
                    continue
                sidecars = _load_sidecars(run_dir)
                for line_index, instance in _read_jsonl(instances_path):
                    request_id = str(instance.get("request_id"))
                    scene_id = str(instance.get("scene_id"))
                    key = (scene_id, request_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(
                        {
                            "class_id": spec["class_id"],
                            "family": spec["family"],
                            "difficulty": spec["difficulty"],
                            "split": split,
                            "seed": seed,
                            "scene_id": scene_id,
                            "request_id": request_id,
                            "instance": instance,
                            "sidecars": sidecars,
                            "run_rel": str(run_dir.relative_to(snapshot_root)),
                            "instances_rel": str(instances_path.relative_to(snapshot_root)),
                            "line_index": line_index,
                        }
                    )
                    break
                if len(found) == 2:
                    break
            if len(found) == 2:
                break
        if len(found) != 2:
            raise SystemExit(f"could not select 2 requests for {spec['class_id']}")
        selected.extend(found)
    return selected


def unique_factors(values: list[Any]) -> list[float]:
    unique: list[float] = []
    for value in values:
        factor = float(value)
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError(f"invalid query factor: {value}")
        if any(abs(factor - existing) <= FACTOR_REL_TOL * max(1.0, abs(existing), abs(factor)) for existing in unique):
            continue
        unique.append(factor)
    return unique


def _seeds(split_dir: Path) -> list[int]:
    if not split_dir.is_dir():
        return []
    seeds = []
    for path in split_dir.iterdir():
        if path.is_dir() and path.name.startswith("seed") and path.name[4:].isdigit():
            seeds.append(int(path.name[4:]))
    return sorted(seeds)


def _load_sidecars(run_dir: Path) -> dict[str, Any]:
    sidecars: dict[str, Any] = {}
    for name in ("config.json", "obstacles.json", "capture_config.json"):
        path = run_dir / name
        if path.is_file():
            sidecars[name] = json.loads(path.read_text())
            sidecars[name.removesuffix(".json")] = sidecars[name]
    return sidecars


def _read_jsonl(path: Path):
    with path.open() as stream:
        for index, line in enumerate(stream):
            if not line.strip():
                continue
            yield index, json.loads(line)


def _validate_table(table: dict[str, Any], selected: list[dict[str, Any]]) -> None:
    rows = table["rows"]
    if len(rows) != 12:
        raise SystemExit("table must contain 12 rows")
    keys = [(row["identity"]["scene_id"], row["identity"]["request_id"]) for row in rows]
    if len(set(keys)) != 12:
        raise SystemExit("selected requests must differ by (scene_id, request_id)")
    by_class = Counter(row["class_id"] for row in rows)
    if set(by_class) != {spec["class_id"] for spec in CLASSES} or any(count != 2 for count in by_class.values()):
        raise SystemExit("table must contain 6 classes x 2 requests")
    for row, item in zip(rows, selected):
        if item["family"] == "static_forest" and not row["same_map_across_seeds"]:
            raise SystemExit("forest rows must record same_map_across_seeds=true")
        original = row["original_factor"]
        times = time_query(
            item["instance"]["n"],
            item["instance"]["initial_dt"],
            item["instance"]["dc"],
            original,
        )
        classifications = {record["factor"]: record["classification"] for record in row["factors"]}
        if "same_factor_reference" not in classifications.values():
            raise SystemExit("each request must have a same_factor_reference query")
        off = [record for record in row["factors"] if abs(record["factor"] - 1.37) <= FACTOR_REL_TOL * max(1.0, 1.37)]
        if len(off) != 1 or off[0]["classification"] != "blocked_missing_observation":
            raise SystemExit("off-grid 1.37 must be blocked_missing_observation")
        if not times["segment_dt"]:
            raise SystemExit("invalid original segment duration")


def readme_text(table: dict[str, Any], missing: dict[str, Any], snapshot_root: Path) -> str:
    union = ", ".join(missing["union"]) or "(none)"
    return f"""# Joint time 12-request small table

Source capture (read-only): `{table["snapshot_root"]}`.
Thresholds: `docker/dev-workspace/results/joint-time-v2/config.json`.
Do not write into the official capture trees.

## How to query

```python
from reconstructable_request import from_planning_instance, query, time_query
snapshot = json.loads(Path("requests/<file>.json").read_text())
print(query(snapshot, 1.37))          # blocked unless observation is complete
print(query(snapshot, snapshot["time_inputs"]["original_factor"], original_instance))
print(time_query(n, initial_dt, dc, 1.37))  # C++ segment_time.hpp formula
```

`time_query` uses `d0 = max(initial_dt, 2*dc)`, `segment_dt = d0 * f`,
`T = n * segment_dt`, layer `i` ends at `(i+1) * segment_dt`.

## What is filled

Each `requests/*.json` is `kind=sando_reconstructable_request`. Identity,
frozen `start[9]` / `goal[9]` (`goal` is planner `local_E`), timestamps,
`n` / `initial_dt` / `dc` / original factor and segment duration, map
bounds, planner/norm, and sidecar spawn `obst_pos` / `obst_bbox` from
`obstacles.json` when present. Forest rows set `same_map_across_seeds=true`
because the world map repeats across seeds.

Same-factor queries (`rel <= 2e-6`) replay the captured instance:
classification `same_factor_reference`, formula check on `segment_dt`,
and copied outcome `status` / `residuals` / `objective`.

## What is blocked

New factors, including off-grid `1.37`, do not call Gurobi. If any rebuild
field is missing the classification is `blocked_missing_observation`.
Voxels are never invented. Union of missing observation fields:

{union}

Counts: `{table["counts"]}`.
"""


if __name__ == "__main__":
    raise SystemExit(main())
