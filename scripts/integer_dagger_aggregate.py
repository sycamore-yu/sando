#!/usr/bin/env python3
"""Aggregate expert labels from student-visited snapshots without mixing eval splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _identity(record: dict[str, Any]) -> tuple[Any, ...]:
    instance = record.get("instance") if isinstance(record.get("instance"), dict) else record
    return tuple(instance.get(name) for name in ("scene_id", "episode_id", "request_id", "factor_id"))


def _split(record: dict[str, Any]) -> str:
    instance = record.get("instance") if isinstance(record.get("instance"), dict) else record
    capture = instance.get("outcome", {}).get("capture", {})
    if not isinstance(capture, dict):
        capture = {}
    return str(capture.get("split") or instance.get("split") or "")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open() as stream:
        for line in stream:
            if line.strip():
                records.append(json.loads(line))
    return records


def aggregate(original: Iterable[dict[str, Any]], extra: Iterable[dict[str, Any]],
              allowed_split: str = "train") -> dict[str, Any]:
    merged = []
    seen = set()
    duplicates = 0
    rejected_split = 0
    sources = {"original": 0, "student": 0}
    for source, records in (("original", original), ("student", extra)):
        for record in records:
            if _split(record) != allowed_split:
                rejected_split += 1
                continue
            key = _identity(record)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            copied = dict(record)
            copied["aggregation_source"] = source
            merged.append(copied)
            sources[source] += 1
    return {
        "records": merged,
        "duplicates": duplicates,
        "rejected_split": rejected_split,
        "sources": sources,
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        for record in records:
            stream.write(json.dumps(record, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", required=True)
    parser.add_argument("--student", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", default="train")
    args = parser.parse_args()
    result = aggregate(load_jsonl(Path(args.original)), load_jsonl(Path(args.student)), args.split)
    write_jsonl(Path(args.output), result["records"])
    Path(args.output).with_suffix(".report.json").write_text(
        json.dumps({key: result[key] for key in ("duplicates", "rejected_split", "sources")}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
