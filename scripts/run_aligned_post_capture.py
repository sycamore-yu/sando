#!/usr/bin/env python3
"""Post-capture stages for process_improvement_v1.

Copies the official aligned snapshot, enqueues offline labels, merges, then
runs one-seed A/B/C training. Does not modify the official capture tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from integer_set_supervision import CONFIG
from integer_label_queue import CACHE_VERSION, queue_lock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_OFFICIAL = ROOT / "docker/results/integer-benchmark-aligned-data"
DEFAULT_EXIT = ROOT / "docker/results/integer-benchmark-aligned-capture.exit"
DEFAULT_WORK = ROOT / "docker/dev-workspace/results/aligned_post_capture"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=cwd)


def verify_capture(official: Path, exit_file: Path) -> dict:
    if not exit_file.is_file():
        raise SystemExit(f"capture exit file missing: {exit_file}")
    code = int(exit_file.read_text().strip() or "1")
    if code != 0:
        raise SystemExit(f"capture exited with status {code}")
    train = sorted(
        int(p.name[4:])
        for p in (official / "train").glob("seed*")
        if p.name[4:].isdigit() and (p / "output.json").is_file()
    )
    val = sorted(
        int(p.name[4:])
        for p in (official / "validation").glob("seed*")
        if p.name[4:].isdigit() and (p / "output.json").is_file()
    ) if (official / "validation").is_dir() else []
    missing_train = [i for i in range(40) if i not in train]
    missing_val = [i for i in range(100, 110) if i not in val]
    report = {
        "exit_code": code,
        "train_seeds": len(train),
        "validation_seeds": len(val),
        "missing_train": missing_train,
        "missing_val": missing_val,
    }
    if missing_train or missing_val:
        raise SystemExit(f"capture incomplete: {json.dumps(report)}")
    # reject invalid seed manifests
    bad = []
    for split, seeds in (("train", train), ("validation", val)):
        for seed in seeds:
            manifest = json.loads((official / split / f"seed{seed}" / "output.json").read_text())
            if manifest.get("required_capture_invalid"):
                bad.append(f"{split}/seed{seed}")
    report["invalid_seeds"] = bad
    if bad:
        raise SystemExit(f"capture has invalid seeds: {bad}")
    return report


def copy_snapshot(official: Path, snapshot: Path) -> None:
    if snapshot.exists():
        raise SystemExit(f"refusing to overwrite snapshot {snapshot}")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(official, snapshot, symlinks=False)
    (snapshot / ".source_manifest.json").write_text(
        json.dumps(snapshot_manifest(official), indent=2) + "\n")


def snapshot_manifest(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): file_sha256(path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != ".source_manifest.json"}


def validate_snapshot(official: Path, snapshot: Path) -> None:
    marker = snapshot / ".source_manifest.json"
    if (not marker.is_file() or
            json.loads(marker.read_text()) != snapshot_manifest(official) or
            json.loads(marker.read_text()) != snapshot_manifest(snapshot)):
        raise SystemExit(f"snapshot does not match official capture: {snapshot}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def labeler_identity(labeler: Path) -> dict[str, str]:
    return {"path": str(labeler.resolve()), "sha256": file_sha256(labeler)}


def label_queue(snapshot: Path, work: Path, labeler: Path, workers: int,
               limit_runs: int | None, pilot_partial: bool = False) -> Path:
    queue = work / "label_queue"
    (queue / "deferred").mkdir(parents=True, exist_ok=True)
    shards = work / "label_shards"
    merged = work / "labels_complete.jsonl"
    run([sys.executable, str(SCRIPTS / "integer_label_queue.py"), "enqueue",
         "--input-root", str(snapshot), "--queue", str(queue),
         "--extra-json", json.dumps({"mode": "complete_cost_table",
                                      "label_version": CACHE_VERSION,
                                      "config": CONFIG,
                                      "labeler": labeler_identity(labeler)})])
    if limit_runs is not None:
        with queue_lock(queue):
            pending = sorted((queue / "pending").glob("*.json"))
            for path in pending[limit_runs:]:
                path.replace(queue / "deferred" / path.name)
    procs = []
    for index in range(max(1, workers)):
        procs.append(subprocess.Popen([
            sys.executable, str(SCRIPTS / "integer_label_queue.py"), "worker",
            "--queue", str(queue), "--work", str(shards),
            "--labeler", str(labeler), "--worker-id", f"w{index}",
        ]))
    codes = [proc.wait() for proc in procs]
    if any(code != 0 for code in codes):
        raise SystemExit(f"label workers failed: {codes}")
    merge_command = [sys.executable, str(SCRIPTS / "integer_label_queue.py"), "merge",
                     "--queue", str(queue), "--output", str(merged)]
    if pilot_partial:
        merge_command.append("--allow-partial")
    run(merge_command)
    return merged


def split_labels(merged: Path, work: Path) -> tuple[Path, Path]:
    train_path = work / "train_labels.jsonl"
    val_path = work / "validation_labels.jsonl"
    with merged.open() as src, train_path.open("w") as train, val_path.open("w") as val:
        for line in src:
            record = json.loads(line)
            split = ((record.get("instance") or {}).get("outcome") or {}).get("capture", {}).get("split")
            if split == "validation":
                val.write(line if line.endswith("\n") else line + "\n")
            elif split == "train":
                train.write(line if line.endswith("\n") else line + "\n")
            else:
                raise RuntimeError(f"label has no valid split: {split!r}")
    return train_path, val_path


def training_dependencies() -> dict:
    import importlib
    import importlib.metadata
    import platform
    versions = {"python": platform.python_version()}
    for package in ("numpy", "torch"):
        try:
            versions[package] = str(importlib.import_module(package).__version__)
        except ImportError:
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
    return versions


def validate_model_reuse(out: Path, train_path: Path, val_path: Path, method: str, seed: int,
                         device: str = "cpu", threads: int = 4) -> dict:
    completed_path = out / "completed.json"
    model = out / "model.json"
    if not completed_path.is_file() or not model.is_file():
        raise RuntimeError(f"incomplete model output: {out}")
    completed = json.loads(completed_path.read_text())
    expected = {"status": "complete", "method": method, "seed": seed,
                "epochs": 100, "completed_epochs": 100, "batch_size": 32,
                "learning_rate": 1e-3, "threads": threads, "device": device,
                "new_data_sha256": None,
                "new_data_sampling": {"enabled": False, "ratio": "50/50", "batch_size": 32},
                "train_data_sha256": file_sha256(train_path),
                "validation_data_sha256": file_sha256(val_path),
                "training_script_sha256": file_sha256(SCRIPTS / "train_integer_corridor_policy.py"),
                "training_batch_sha256": file_sha256(SCRIPTS / "integer_corridor_training_batch.py"),
                "policy_source_sha256": file_sha256(SCRIPTS / "integer_corridor_policy.py"),
                "set_supervision_sha256": file_sha256(SCRIPTS / "integer_set_supervision.py"),
                "supervision_config": CONFIG, "model_sha256": file_sha256(model),
                "dependencies": training_dependencies()}
    different = [key for key, value in expected.items() if completed.get(key) != value]
    if different:
        raise RuntimeError(f"stale model output {out}: {', '.join(different)}")
    return completed


def train_abc(train_path: Path, val_path: Path, work: Path, seed: int = 0,
              device: str = "cpu", threads: int = 4) -> dict:
    results = {}
    for method in ("bc", "cost", "set", "objective"):
        out = work / f"model_{method}_seed{seed}"
        if out.exists():
            completed = validate_model_reuse(out, train_path, val_path, method, seed, device, threads)
            results[method] = {
                "best_epoch": completed.get("best_epoch"),
                "best_validation_metric": completed.get("best_validation_metric"),
                "output": str(out),
            }
            continue
        run([
            sys.executable, str(SCRIPTS / "train_integer_corridor_policy.py"),
            "--train", str(train_path), "--validation", str(val_path),
            "--output", str(out), "--method", method, "--seed", str(seed), "--threads", str(threads),
            "--device", device,
        ])
        completed = validate_model_reuse(out, train_path, val_path, method, seed, device, threads)
        results[method] = {
            "best_epoch": completed.get("best_epoch"),
            "best_validation_metric": completed.get("best_validation_metric"),
            "output": str(out),
        }
    (work / f"training_seed{seed}_summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, default=DEFAULT_OFFICIAL)
    parser.add_argument("--exit-file", type=Path, default=DEFAULT_EXIT)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--labeler", type=Path,
                        default=ROOT / "docker/dev-workspace/install/sando/lib/sando/label_planning_instances")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit-runs", type=int, default=None,
                        help="optional cap on labelled runs for a pilot")
    parser.add_argument("--pilot-partial", action="store_true",
                        help="allow incomplete label queues for an explicit pilot")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--training-seeds", nargs="+", type=int, choices=(0, 1, 2), default=[0, 1, 2])
    parser.add_argument("--wait-exit", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=3600 * 6)
    args = parser.parse_args()

    if args.wait_exit:
        deadline = time.time() + args.wait_seconds
        while not args.exit_file.is_file():
            if time.time() > deadline:
                raise SystemExit("timed out waiting for capture exit")
            print(f"[wait] no exit yet; sleep 60s", flush=True)
            time.sleep(60)

    report = verify_capture(args.official, args.exit_file)
    work = args.work
    work.mkdir(parents=True, exist_ok=True)
    (work / "capture_verify.json").write_text(json.dumps(report, indent=2) + "\n")
    snapshot = work / "snapshot"
    if not snapshot.exists():
        copy_snapshot(args.official, snapshot)
    else:
        validate_snapshot(args.official, snapshot)
    if not args.labeler.is_file():
        raise SystemExit(f"labeler missing: {args.labeler}")
    if args.limit_runs is not None and not args.pilot_partial:
        raise SystemExit("--limit-runs requires explicit --pilot-partial")
    merged = label_queue(snapshot, work, args.labeler, args.workers, args.limit_runs,
                         pilot_partial=args.pilot_partial)
    train_path, val_path = split_labels(merged, work)
    summary = {"capture": report, "labels": str(merged), "train": str(train_path), "validation": str(val_path)}
    if not args.skip_train:
        summary["training"] = {str(seed): train_abc(train_path, val_path, work, seed=seed)
                               for seed in args.training_seeds}
    (work / "post_capture_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
