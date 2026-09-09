#!/usr/bin/env python3
"""Resumable local labeling queue. Source snapshots are never modified.

A queue-wide flock serializes state transitions; per-task flocks stay open in
both worker and solver, so recovery cannot restart a surviving orphan solver.
The immutable task inventory makes missing tasks distinguishable from success.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import uuid
from typing import Any

from integer_set_supervision import CONFIG

CACHE_VERSION = "label_queue_v2"
STATES = ("pending", "claimed", "done", "failed", "deferred")
IDENTITY_KEYS = ("scene_id", "episode_id", "request_id", "factor_id")
# The descriptor is deliberately not serialized into task/report JSON.
_CLAIM_LOCKS: dict[str, Any] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def queue_lock(queue_dir: Path):
    queue_dir.mkdir(parents=True, exist_ok=True)
    with (queue_dir / ".lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def task_lock(queue_dir: Path, task_id: str):
    handle = (queue_dir / "locks" / task_id).open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def snapshot_fingerprint(instances: Path, summary: Path | None, extra: dict[str, Any]) -> str:
    payload = {"instances": sha256_file(instances),
               "summary": sha256_file(summary) if summary and summary.is_file() else None,
               "extra": extra, "cache_version": CACHE_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def seed_complete(seed_dir: Path) -> bool:
    return (seed_dir / "output.json").is_file()


def iter_completed_runs(root: Path) -> list[Path]:
    runs = []
    for split in ("train", "validation"):
        for seed_dir in sorted((root / split).glob("seed*")):
            if not re.fullmatch(r"seed\d+", seed_dir.name) or not seed_complete(seed_dir):
                continue
            manifest = json.loads((seed_dir / "output.json").read_text())
            if manifest.get("required_capture_invalid"):
                raise RuntimeError(f"invalid capture seed: {seed_dir}")
            recorded = manifest.get("runs")
            expected = None if recorded is None else {
                Path(entry["input"]["output"]).name for entry in recorded}
            actual = {p.name for p in (seed_dir / "runs").iterdir() if p.is_dir()}
            if expected is not None and actual != expected:
                raise RuntimeError(f"capture run inventory mismatch: {seed_dir}")
            for name in sorted(actual):
                run_dir = seed_dir / "runs" / name
                if not all((run_dir / p).is_file() for p in ("instances.jsonl", "result.json")):
                    raise RuntimeError(f"incomplete capture run: {run_dir}")
                runs.append(run_dir)
    return runs


def enqueue(root: Path, queue_dir: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = {"mode": "complete_cost_table", "label_version": CACHE_VERSION,
             "config": CONFIG, **(extra or {})}
    created = []
    with queue_lock(queue_dir):
        for state in (*STATES, "tasks", "locks"):
            (queue_dir / state).mkdir(exist_ok=True)
        for run_dir in iter_completed_runs(root):
            instances = run_dir / "instances.jsonl"
            summary = run_dir / "instances.jsonl.summary.json"
            fingerprint = snapshot_fingerprint(instances, summary, extra)
            task = {"id": fingerprint, "source_run": str(run_dir.resolve()),
                    "instances": str(instances.resolve()),
                    "summary": str(summary.resolve()) if summary.is_file() else None,
                    "instances_sha256": sha256_file(instances),
                    "fingerprint": fingerprint, "extra": extra}
            inventory = queue_dir / "tasks" / f"{fingerprint}.json"
            if not inventory.exists():
                atomic_json(inventory, task)
                created.append(fingerprint)
            elif json.loads(inventory.read_text()) != task:
                raise RuntimeError(f"task identity collision: {fingerprint}")
            # Also repairs an enqueue interrupted after inventory publication.
            if not any((queue_dir / state / inventory.name).exists() for state in STATES):
                atomic_json(queue_dir / "pending" / inventory.name, task)
    return {"enqueued": created,
            "pending": len(list((queue_dir / "pending").glob("*.json")))}


def claim(queue_dir: Path, worker: str) -> dict[str, Any] | None:
    with queue_lock(queue_dir):
        for path in sorted((queue_dir / "pending").glob("*.json")):
            if (queue_dir / "claimed" / path.name).exists():
                raise RuntimeError(f"duplicate task state: {path.name}")
            handle = task_lock(queue_dir, path.stem)
            if handle is None:
                continue
            try:
                task = json.loads((queue_dir / "tasks" / path.name).read_text())
                token = uuid.uuid4().hex
                task.update(worker=worker, claim_file=path.name, claim_token=token,
                            pid=os.getpid(), hostname=socket.gethostname(), claimed_utc=time.time())
                # A crash before rename leaves a valid pending record. A crash
                # after rename leaves complete owner metadata; never truncate a claim.
                atomic_json(path, task)
                os.replace(path, queue_dir / "claimed" / path.name)
                _CLAIM_LOCKS[token] = handle
                return task
            except BaseException:
                handle.close()
                raise
    return None


def _instances(path: Path) -> dict[tuple[str, ...], dict[str, Any]]:
    result = {}
    with path.open() as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            instance = record.get("instance", record)
            key = tuple(instance.get(name) for name in IDENTITY_KEYS)
            if any(not isinstance(value, str) or not value for value in key) or key in result:
                raise RuntimeError(f"invalid or duplicate planning instance: {path}")
            result[key] = instance
    return result


def validate_output(task: dict[str, Any], output: Path) -> None:
    source = Path(task["instances"])
    if sha256_file(source) != task["instances_sha256"]:
        raise RuntimeError("source snapshot changed after enqueue")
    expected = _instances(source)
    actual = _instances(output)
    if expected != actual:
        raise RuntimeError("label output does not preserve every input planning instance")


def run_labeler(task: dict[str, Any], work_dir: Path, labeler: Path,
                extra_args: list[str] | None = None) -> dict[str, Any]:
    source = Path(task["instances"])
    if sha256_file(source) != task["instances_sha256"]:
        raise RuntimeError("source snapshot changed after enqueue")
    expected_labeler = task.get("extra", {}).get("labeler")
    if expected_labeler and sha256_file(labeler) != expected_labeler["sha256"]:
        raise RuntimeError("labeler executable changed after enqueue")
    shard = work_dir / task["id"]
    shard.mkdir(parents=True, exist_ok=True)
    input_copy = shard / "instances.jsonl"
    if not input_copy.exists():
        temporary = shard / f".input.{uuid.uuid4().hex}.tmp"
        shutil.copyfile(source, temporary)
        os.replace(temporary, input_copy)
    if sha256_file(input_copy) != task["instances_sha256"]:
        raise RuntimeError("copied snapshot does not match source")
    token = task.get("claim_token", uuid.uuid4().hex)
    output = shard / f"labels-{token}.jsonl"
    handle = _CLAIM_LOCKS.get(token)
    passed_fds = (handle.fileno(),) if handle else ()
    command = [str(labeler), "--input", str(input_copy), "--output", str(output), *(extra_args or [])]
    started = time.monotonic()
    completed = subprocess.run(command, check=False, capture_output=True, text=True,
                               pass_fds=passed_fds)
    if completed.returncode == 0:
        validate_output(task, output)
    return {"task": task, "returncode": completed.returncode,
            "wall_seconds": time.monotonic() - started,
            "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-4000:],
            "output": str(output) if output.is_file() else None,
            "input_sha256": sha256_file(input_copy),
            "output_sha256": sha256_file(output) if output.is_file() else None}


def publish(queue_dir: Path, report: dict[str, Any]) -> None:
    task = report["task"]
    token = task["claim_token"]
    try:
        with queue_lock(queue_dir):
            claimed = queue_dir / "claimed" / task["claim_file"]
            if json.loads(claimed.read_text()).get("claim_token") != token:
                raise RuntimeError("task claim ownership changed")
            state = "done" if report["returncode"] == 0 and report.get("output_sha256") else "failed"
            atomic_json(queue_dir / state / claimed.name, report)
            claimed.unlink()
    finally:
        handle = _CLAIM_LOCKS.pop(token, None)
        if handle is not None:
            handle.close()


def recover(queue_dir: Path, worker: str, task_id: str | None = None) -> int:
    """Recover only claims whose worker AND solver no longer hold their lock."""
    recovered = 0
    with queue_lock(queue_dir):
        for path in sorted((queue_dir / "claimed").glob("*.json")):
            task = json.loads(path.read_text())
            if task.get("worker") != worker or (task_id and task["id"] != task_id):
                continue
            handle = task_lock(queue_dir, task["id"])
            if handle is None:
                continue
            try:
                terminal = [queue_dir / state / path.name for state in ("done", "failed")
                            if (queue_dir / state / path.name).exists()]
                if terminal:
                    if len(terminal) != 1 or json.loads(terminal[0].read_text())["task"]["claim_token"] != task["claim_token"]:
                        raise RuntimeError("conflicting completed claim")
                    path.unlink()  # interrupted after terminal report publication
                    continue
                if sha256_file(Path(task["instances"])) != task["instances_sha256"]:
                    raise RuntimeError(f"claim source changed: {path.name}")
                # Keep owner metadata until the atomic move; clearing it in
                # claimed would introduce another unrecoverable crash window.
                os.replace(path, queue_dir / "pending" / path.name)
                recovered += 1
            finally:
                handle.close()
    return recovered


def worker_loop(queue_dir: Path, work_dir: Path, labeler: Path, worker: str,
                once: bool = False) -> int:
    processed = failures = 0
    while (task := claim(queue_dir, worker)) is not None:
        try:
            report = run_labeler(task, work_dir, labeler)
        except Exception as error:
            report = {"task": task, "returncode": 1, "error": str(error), "output": None,
                      "output_sha256": None}
        failures += bool(report["returncode"] != 0 or not report.get("output"))
        publish(queue_dir, report)
        processed += 1
        if once:
            break
    return -failures if failures else processed


def merge(queue_dir: Path, output: Path, allow_partial: bool = False) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    counts = {"done": 0, "failed": 0, "duplicate": 0, "unknown": 0,
              "partial": allow_partial}
    try:
        with queue_lock(queue_dir):
            expected = {p.stem for p in (queue_dir / "tasks").glob("*.json")}
            states = {s: {p.stem for p in (queue_dir / s).glob("*.json")} for s in STATES}
            active = set().union(*(states[s] for s in STATES if s != "done"))
            if not expected or set().union(*states.values()) != expected:
                raise RuntimeError("queue task inventory is missing or inconsistent")
            if not allow_partial and (active or states["done"] != expected):
                raise RuntimeError("queue incomplete: " + " ".join(f"{s}={len(states[s])}" for s in STATES))
            counts["failed"] = len(states["failed"])
            seen = set()
            with temporary.open("x") as stream:
                for task_id in sorted(states["done"]):
                    report = json.loads((queue_dir / "done" / f"{task_id}.json").read_text())
                    labels = Path(report["output"]) if report.get("output") else None
                    try:
                        if (report.get("returncode") != 0 or labels is None or not labels.is_file()
                                or sha256_file(labels) != report.get("output_sha256")
                                or report.get("input_sha256") != report["task"]["instances_sha256"]):
                            raise RuntimeError("completed label hash mismatch")
                        validate_output(report["task"], labels)
                    except (OSError, ValueError, RuntimeError) as error:
                        if not allow_partial:
                            raise RuntimeError(f"invalid completed labels: {task_id}: {error}") from error
                        counts["failed"] += 1
                        continue
                    with labels.open() as source:
                        for line in source:
                            if not line.strip():
                                continue
                            record = json.loads(line)
                            instance = record.get("instance", record)
                            key = tuple(instance[name] for name in IDENTITY_KEYS)
                            if key in seen:
                                raise RuntimeError(f"duplicate planning instance across tasks: {key}")
                            seen.add(key)
                            counts["unknown"] += record.get("excluded_reason") == "unknown_or_infeasible_results"
                            stream.write(json.dumps(record, allow_nan=False) + "\n")
                            counts["done"] += 1
                stream.flush()
                os.fsync(stream.fileno())
            if output.exists():
                if sha256_file(output) != sha256_file(temporary):
                    raise RuntimeError(f"refusing to overwrite different merged labels: {output}")
                temporary.unlink()
            else:
                os.replace(temporary, output)
            counts.update(expected_tasks=len(expected), completed_tasks=len(states["done"]),
                          output_sha256=sha256_file(output))
            atomic_json(queue_dir / "merge_report.json", counts)
    finally:
        temporary.unlink(missing_ok=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("enqueue", "worker", "merge", "recover"))
    parser.add_argument("--input-root")
    parser.add_argument("--queue", required=True)
    parser.add_argument("--work")
    parser.add_argument("--labeler")
    parser.add_argument("--output")
    parser.add_argument("--worker-id", default="worker0")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--task-id")
    parser.add_argument("--extra-json")
    args = parser.parse_args()
    queue = Path(args.queue)
    if args.command == "enqueue":
        if not args.input_root:
            parser.error("enqueue requires --input-root")
        print(json.dumps(enqueue(Path(args.input_root), queue,
                                 json.loads(args.extra_json) if args.extra_json else None)))
        return 0
    if args.command == "worker":
        if not args.work or not args.labeler:
            parser.error("worker requires --work and --labeler")
        processed = worker_loop(queue, Path(args.work), Path(args.labeler), args.worker_id, args.once)
        print(json.dumps({"processed": abs(processed), "failed": max(0, -processed)}))
        return int(processed < 0)
    if args.command == "recover":
        print(json.dumps({"recovered": recover(queue, args.worker_id, args.task_id)}))
        return 0
    if not args.output:
        parser.error("merge requires --output")
    print(json.dumps(merge(queue, Path(args.output), args.allow_partial)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
