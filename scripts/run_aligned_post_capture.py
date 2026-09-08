#!/usr/bin/env python3
"""Post-capture stages for process_improvement_v1.

Copies the official aligned snapshot, enqueues offline labels, merges, then
runs one-seed A/B/C training. Does not modify the official capture tree.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

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


def label_queue(snapshot: Path, work: Path, labeler: Path, workers: int, limit_runs: int | None) -> Path:
    queue = work / "label_queue"
    shards = work / "label_shards"
    merged = work / "labels_complete.jsonl"
    run([sys.executable, str(SCRIPTS / "integer_label_queue.py"), "enqueue",
         "--input-root", str(snapshot), "--queue", str(queue)])
    if limit_runs is not None:
        pending = sorted((queue / "pending").glob("*.json"))
        for path in pending[limit_runs:]:
            path.unlink()
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
    run([sys.executable, str(SCRIPTS / "integer_label_queue.py"), "merge",
         "--queue", str(queue), "--output", str(merged)])
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
            else:
                train.write(line if line.endswith("\n") else line + "\n")
    return train_path, val_path


def train_abc(train_path: Path, val_path: Path, work: Path, seed: int = 0) -> dict:
    results = {}
    for method in ("bc", "cost", "set"):
        out = work / f"model_{method}_seed{seed}"
        if out.exists():
            shutil.rmtree(out)
        run([
            sys.executable, str(SCRIPTS / "train_integer_corridor_policy.py"),
            "--train", str(train_path), "--validation", str(val_path),
            "--output", str(out), "--method", method, "--seed", str(seed), "--threads", "4",
        ])
        completed = json.loads((out / "completed.json").read_text())
        results[method] = {
            "best_epoch": completed.get("best_epoch"),
            "best_validation_metric": completed.get("best_validation_metric"),
            "output": str(out),
        }
    (work / "abc_seed0_summary.json").write_text(json.dumps(results, indent=2) + "\n")
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
    parser.add_argument("--skip-train", action="store_true")
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
    if not args.labeler.is_file():
        raise SystemExit(f"labeler missing: {args.labeler}")
    merged = label_queue(snapshot, work, args.labeler, args.workers, args.limit_runs)
    train_path, val_path = split_labels(merged, work)
    summary = {"capture": report, "labels": str(merged), "train": str(train_path), "validation": str(val_path)}
    if not args.skip_train:
        summary["abc"] = train_abc(train_path, val_path, work, seed=0)
    (work / "post_capture_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
