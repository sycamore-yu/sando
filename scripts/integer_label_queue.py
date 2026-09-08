#!/usr/bin/env python3
"""File-queue labelling of completed capture snapshots. Does not modify official outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from integer_set_supervision import CONFIG

CACHE_VERSION = "label_queue_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_fingerprint(instances: Path, summary: Path | None, extra: dict[str, Any]) -> str:
    payload = {
        "instances": sha256_file(instances),
        "summary": sha256_file(summary) if summary and summary.is_file() else None,
        "extra": extra,
        "cache_version": CACHE_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def seed_complete(seed_dir: Path) -> bool:
    return (seed_dir / "output.json").is_file()


def iter_completed_runs(root: Path) -> list[Path]:
    runs = []
    for split in ("train", "validation"):
        split_dir = root / split
        if not split_dir.is_dir():
            continue
        for seed_dir in sorted(split_dir.glob("seed*")):
            if not seed_complete(seed_dir):
                continue
            for run_dir in sorted((seed_dir / "runs").glob("*")):
                if (run_dir / "instances.jsonl").is_file() and (run_dir / "result.json").is_file():
                    runs.append(run_dir)
    return runs


def enqueue(root: Path, queue_dir: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "pending").mkdir(exist_ok=True)
    (queue_dir / "claimed").mkdir(exist_ok=True)
    (queue_dir / "done").mkdir(exist_ok=True)
    (queue_dir / "failed").mkdir(exist_ok=True)
    extra = extra or {"mode": "complete_cost_table", "label_version": CACHE_VERSION}
    created = []
    for run_dir in iter_completed_runs(root):
        instances = run_dir / "instances.jsonl"
        summary = run_dir / "instances.jsonl.summary.json"
        fingerprint = snapshot_fingerprint(instances, summary, extra)
        task = {
            "id": fingerprint,
            "source_run": str(run_dir.resolve()),
            "instances": str(instances.resolve()),
            "summary": str(summary.resolve()) if summary.is_file() else None,
            "instances_sha256": sha256_file(instances),
            "fingerprint": fingerprint,
            "extra": extra,
        }
        pending = queue_dir / "pending" / f"{fingerprint}.json"
        done = queue_dir / "done" / f"{fingerprint}.json"
        if done.is_file() or pending.is_file():
            continue
        tmp = queue_dir / "pending" / f".{fingerprint}.tmp"
        tmp.write_text(json.dumps(task, indent=2) + "\n")
        tmp.replace(pending)
        created.append(fingerprint)
    return {"enqueued": created, "pending": len(list((queue_dir / "pending").glob("*.json")))}


def claim(queue_dir: Path, worker: str) -> dict[str, Any] | None:
    pending = queue_dir / "pending"
    for path in sorted(pending.glob("*.json")):
        claimed = queue_dir / "claimed" / path.name
        try:
            os.rename(path, claimed)
        except FileNotFoundError:
            continue
        task = json.loads(claimed.read_text())
        task["worker"] = worker
        task["claimed_utc"] = time.time()
        claimed.write_text(json.dumps(task, indent=2) + "\n")
        return task
    return None


def run_labeler(task: dict[str, Any], work_dir: Path, labeler: Path, extra_args: list[str] | None = None) -> dict[str, Any]:
    shard = work_dir / task["id"]
    shard.mkdir(parents=True, exist_ok=True)
    input_copy = shard / "instances.jsonl"
    current = sha256_file(Path(task["instances"]))
    expected = task["instances_sha256"]
    if current != expected:
        raise RuntimeError("source snapshot changed after enqueue")
    if not input_copy.exists():
        shutil.copy2(task["instances"], input_copy)
    if sha256_file(input_copy) != current:
        raise RuntimeError("copied snapshot does not match source")
    output = shard / "labels.jsonl"
    if output.exists():
        output.unlink()
    command = [str(labeler), "--input", str(input_copy), "--output", str(output)]
    command.extend(extra_args or [])
    started = time.time()
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    report = {
        "task": task,
        "returncode": completed.returncode,
        "wall_seconds": time.time() - started,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "output": str(output) if output.is_file() else None,
        "input_sha256": sha256_file(input_copy),
        "output_sha256": sha256_file(output) if output.is_file() else None,
    }
    return report


def publish(queue_dir: Path, report: dict[str, Any]) -> None:
    fingerprint = report["task"]["id"]
    claimed = queue_dir / "claimed" / f"{fingerprint}.json"
    destination_dir = queue_dir / ("done" if report["returncode"] == 0 and report["output"] else "failed")
    destination = destination_dir / f"{fingerprint}.json"
    tmp = destination_dir / f".{fingerprint}.tmp"
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(destination)
    if claimed.exists():
        claimed.unlink()


def worker_loop(queue_dir: Path, work_dir: Path, labeler: Path, worker: str, once: bool = False) -> int:
    processed = 0
    while True:
        task = claim(queue_dir, worker)
        if task is None:
            break
        report = run_labeler(task, work_dir, labeler)
        publish(queue_dir, report)
        processed += 1
        if once:
            break
    return processed


def merge(queue_dir: Path, output: Path) -> dict[str, Any]:
    seen = set()
    counts = {"done": 0, "failed": 0, "duplicate": 0, "unknown": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        for path in sorted((queue_dir / "done").glob("*.json")):
            report = json.loads(path.read_text())
            labels = Path(report["output"]) if report.get("output") else None
            if labels is None or not labels.is_file():
                counts["failed"] += 1
                continue
            for line in labels.read_text().splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                instance = record.get("instance") or {}
                key = tuple(instance.get(name) for name in ("scene_id", "episode_id", "request_id", "factor_id"))
                if key in seen:
                    counts["duplicate"] += 1
                    continue
                seen.add(key)
                if record.get("excluded_reason") == "unknown_or_infeasible_results":
                    counts["unknown"] += 1
                stream.write(json.dumps(record, allow_nan=False) + "\n")
                counts["done"] += 1
    for path in (queue_dir / "failed").glob("*.json"):
        counts["failed"] += 1
    (queue_dir / "merge_report.json").write_text(json.dumps(counts, indent=2) + "\n")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("enqueue", "worker", "merge"))
    parser.add_argument("--input-root")
    parser.add_argument("--queue", required=True)
    parser.add_argument("--work")
    parser.add_argument("--labeler")
    parser.add_argument("--output")
    parser.add_argument("--worker-id", default="worker0")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    queue = Path(args.queue)
    if args.command == "enqueue":
        if not args.input_root:
            parser.error("enqueue requires --input-root")
        print(json.dumps(enqueue(Path(args.input_root), queue)))
        return 0
    if args.command == "worker":
        if not args.work or not args.labeler:
            parser.error("worker requires --work and --labeler")
        processed = worker_loop(queue, Path(args.work), Path(args.labeler), args.worker_id, once=args.once)
        print(json.dumps({"processed": processed}))
        return 0
    if not args.output:
        parser.error("merge requires --output")
    print(json.dumps(merge(queue, Path(args.output))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
