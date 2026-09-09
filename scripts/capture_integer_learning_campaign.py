#!/usr/bin/env python3
"""Run the locked integer-learning capture campaign.

This orchestrator owns only its per-run directories and never performs process
cleanup outside the baseline runner.  It deliberately stops at capture for
stage verification; labelling and training are separate stages.
"""

import argparse
import contextlib
import fcntl
import functools
import hashlib
import json
import os
import random
import shutil
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from integer_scene_protocol import (
    aligned_scene_configs,
    randomization_for_split,
    scene_id as protocol_scene_id,
)
from integer_instance_sampler import select_instances

BASELINE = Path(__file__).with_name("integer_learning_baseline_sim.py")
SEEDS = {
    "train": tuple(range(40)),
    "validation": tuple(range(100, 110)),
    "test": tuple(range(200, 230)),
}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "size": path.stat().st_size}


def _artifact_hashes(directory):
    return {
        str(path.relative_to(directory)): _sha256(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "completed.json"
    }


def _load_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path, value, exclusive=False):
    if exclusive:
        mode = "x"
        target = path
    else:
        mode = "w"
        target = path.with_name(path.name + ".tmp")
    with target.open(mode, encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if not exclusive:
        os.replace(target, path)


def _file_identity(path):
    return {"path": str(path.resolve()), **_sha256(path)}


def _campaign_identity(args, configs):
    policy = getattr(args, "policy", None)
    return {
        "split": args.split, "round": args.round,
        "collection_role": getattr(args, "collection_role", "initial" if args.round == 0 else "student_dagger"),
        "counts": list(args.counts), "ratios": list(args.ratios),
        "seeds": [c["seed"] for c in configs],
        "pilot": bool(getattr(args, "pilot", False)),
        "method": getattr(args, "method", "original"),
        "policy": _file_identity(policy.resolve()) if policy else None,
        "setup_bash": _file_identity(args.setup_bash.resolve()),
        "runtime": _runtime_identity(args),
        "baseline_runner": _file_identity(BASELINE),
        "protocol": getattr(args, "protocol", "legacy"),
        "scene_families": getattr(args, "scene_families", None),
        "start_randomization": getattr(args, "start_randomization", None),
        "capture_capacity": getattr(args, "capture_capacity", None),
        "sampling_protocol": getattr(args, "sampling_protocol", None) or "uniform_reservoir_v1",
        "replan_metrics": bool(getattr(args, "replan_metrics", False)),
        "configs": configs,
}


def _runtime_identity(args):
    resolver = getattr(args, "runtime_identity_resolver", None)
    if resolver is not None:
        return resolver(args.setup_bash.resolve())
    command = ["bash", "-lc", f"source {shlex.quote(str(args.setup_bash.resolve()))} && ros2 pkg prefix sando"]
    prefix = subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
    prefix_path = Path(prefix)
    binary = prefix_path / "lib" / "sando" / "sando"
    manifest = prefix_path / "share" / "sando" / "package.xml"
    config = prefix_path / "share" / "sando" / "config"
    if not binary.is_file() or not manifest.is_file():
        raise ValueError("installed sando runtime identity is incomplete")
    return {"prefix": str(prefix_path), "binary": _sha256(binary),
            "package_manifest": _sha256(manifest),
            "source_manifest": _sha256(Path("/opt/sando-integer-source.json")) if Path("/opt/sando-integer-source.json").is_file() else None,
            "config": _artifact_hashes(config) if config.is_dir() else None,
            "campaign_script": _sha256(Path(__file__))}


def _with_campaign_lock(function):
    @functools.wraps(function)
    def wrapped(args):
        output = args.output.resolve()
        existed = output.exists()
        if existed and not getattr(args, "resume", False):
            raise ValueError(f"output directory already exists: {output}; use --resume")
        output.mkdir(parents=True, exist_ok=True)
        lock = _acquire_lock(output)
        args.campaign_lock_fd = lock.fileno()
        try:
            return function(args)
        finally:
            # A surviving baseline child retains this lock after parent death.
            # Closing our descriptor must not explicitly unlock the child's fd.
            lock.close()
            del args.campaign_lock_fd
    return wrapped


def _acquire_lock(output):
    lock = output / ".campaign.lock"
    descriptor = lock.open("a+")
    try:
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        descriptor.close()
        raise ValueError(f"campaign directory is locked: {lock}")
    descriptor.seek(0)
    descriptor.truncate()
    descriptor.write(str(os.getpid()) + "\n")
    descriptor.flush()
    return descriptor


def _quarantine(run_dir, output):
    attempts = output / "attempts"
    attempts.mkdir(exist_ok=True)
    target = attempts / f"{run_dir.name}-{time.time_ns()}"
    shutil.move(str(run_dir), str(target))


def _manifest_valid(manifest, output):
    if manifest.get("required_capture_invalid") or not manifest.get("completed"):
        return False
    aggregate = output / "instances.jsonl"
    if not aggregate.is_file() or manifest.get("instances", {}).get("sha256") != _sha256(aggregate)["sha256"]:
        return False
    entries = manifest.get("runs", [])
    if not entries:
        return False
    expected = {config["scene_id"] for config in manifest.get("identity", {}).get("configs", [])}
    actual = {Path(entry["input"]["output"]).name for entry in entries}
    if not actual <= expected or (not manifest.get("requested", {}).get("pilot") and actual != expected):
        return False
    for entry in manifest.get("runs", []):
        run_dir = Path(entry["input"]["output"])
        if not run_dir.is_dir() or entry.get("artifact_hash") != _artifact_hashes(run_dir):
            return False
        receipt = run_dir / "completed.json"
        if not receipt.is_file():
            return False
        try:
            saved = _load_json(receipt)
        except (OSError, json.JSONDecodeError):
            return False
        if saved.get("identity") != manifest.get("identity") or saved.get("artifact_hash") != _artifact_hashes(run_dir):
            return False
    return True


def _requested_seeds(split, seeds=None):
    """Validate seeds and preserve the caller's order for reproducibility."""
    selected = list(SEEDS[split] if seeds is None else seeds)
    if not selected:
        raise ValueError("--seeds must contain at least one seed")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in selected):
        raise ValueError("--seeds must contain integers")
    if len(set(selected)) != len(selected):
        raise ValueError("--seeds must not contain duplicates")
    allowed = set(SEEDS[split])
    if any(seed not in allowed for seed in selected):
        raise ValueError(f"--seeds contains a seed outside the {split} split")
    return selected


def scene_configs(split, counts, ratios, seeds=None):
    selected_seeds = _requested_seeds(split, seeds)
    return [
        {"split": split, "seed": seed, "num_obstacles": count, "dynamic_ratio": ratio}
        for seed in selected_seeds
        for count in counts
        for ratio in ratios
    ]


def _capture_rows(run_dir):
    path = run_dir / "instances.jsonl"
    if not path.is_file():
        return [], None, "capturemissing: instances.jsonl"
    rows = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"line {line_number} is not an object")
                rows.append(row)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return [], None, f"invalid_capture: {error}"
    sidecar = path.with_name(path.name + ".summary.json")
    if not sidecar.is_file():
        return rows, None, "capturemissing: instances.jsonl.summary.json"
    try:
        summary = _load_json(sidecar)
    except (OSError, json.JSONDecodeError) as error:
        return rows, None, f"invalid_capture_summary: {error}"
    return rows, summary, None


def _validate_capture_rows(rows, summary, result, config, capture_round):
    capture = result.get("capture") or {}
    expected_scene = config.get("scene_id") or (
        f"n{config['num_obstacles']}-d{config['dynamic_ratio']:g}-seed{config['seed']}"
    )
    if not capture.get("source_id") or not capture.get("config_id"):
        return "invalid_capture_metadata: runner capture metadata is missing"
    summary_metadata = (summary or {}).get("metadata") or {}
    for key in ("scene_id", "source_id", "config_id"):
        if not summary_metadata or summary_metadata.get(key) != (expected_scene if key == "scene_id" else capture.get(key)):
            return f"invalid_capture_metadata: {key} disagrees with runner result"
    for row in rows:
        if row.get("schema_version") != 1:
            return "invalid_capture_row: schema_version must be 1"
        for key in ("scene_id", "episode_id", "request_id", "factor_id"):
            if not isinstance(row.get(key), str) or not row[key]:
                return f"invalid_capture_row: {key} must be a nonempty string"
        if row["scene_id"] != expected_scene:
            return "invalid_capture_row: scene_id does not match requested scene"
        if row.get("source_id") != capture["source_id"] or row.get("config_id") != capture["config_id"]:
            return "invalid_capture_row: source/config identity mismatch"
        capture_info = (row.get("outcome") or {}).get("capture")
        if not isinstance(capture_info, dict) or capture_info.get("split") != config["split"] or capture_info.get("capture_round") != capture_round:
            return "invalid_capture_row: outcome.capture split/round mismatch"
    return None


def _row_key(row):
    return tuple(row.get(key) for key in ("scene_id", "episode_id", "request_id", "factor_id"))


def _episode_key(row):
    return (row.get("scene_id"), row.get("episode_id"))


def _pilot_select(rows, target=100, seed=0):
    """Keep complete earlier episodes and sample only the final needed episode."""
    if len(rows) <= target:
        return list(rows)
    groups = []
    for row in rows:
        key = _episode_key(row)
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(row)
    selected = []
    for _, group in groups[:-1]:
        selected.extend(group)
    needed = target - len(selected)
    if needed < 0:
        return random.Random(seed).sample(rows, target)
    selected.extend(random.Random(seed).sample(groups[-1][1], min(needed, len(groups[-1][1]))))
    return selected[:target]


def _run_config(config, output, setup_bash, capture_round, capture_capacity=None,
                sampling_protocol="uniform_reservoir_v1", identity=None, resume=False, lock_fd=None,
                replan_metrics=False):
    run_name = config.get("scene_id") or (
        f"seed{config['seed']}_n{config['num_obstacles']}_d{config['dynamic_ratio']:g}"
    )
    run_dir = output / "runs" / run_name
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    receipt = run_dir / "completed.json"
    if run_dir.exists():
        if not resume:
            raise ValueError(f"run directory already exists; use --resume: {run_dir}")
        if receipt.is_file():
            try:
                saved = _load_json(receipt)
                if saved.get("identity") != identity:
                    raise ValueError(f"completed run identity mismatch: {run_name}")
                if saved.get("artifact_hash") != _artifact_hashes(run_dir):
                    raise ValueError(f"completed run artifacts changed or corrupted: {run_name}")
                saved_entry = saved["entry"]
                rows, summary, capture_error = _capture_rows(run_dir)
                if capture_error or _validate_capture_rows(rows, summary, saved_entry.get("result", {}), config, capture_round):
                    raise ValueError(f"completed run artifacts invalid: {run_name}")
                return {**saved_entry, "rows": rows}
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(f"invalid completed receipt for {run_name}: {error}")
        _quarantine(run_dir, output)
    run_dir.mkdir(parents=True)
    command = [
        sys.executable, str(BASELINE), "--output", str(run_dir),
        "--setup-bash", str(setup_bash), "--seed", str(config["seed"]),
        "--num-obstacles", str(config["num_obstacles"]), "--dynamic-ratio",
        str(config["dynamic_ratio"]), "--capture", "--capture-round", str(capture_round),
        "--scene-family", str(config.get("family", "unknown_dynamic")),
        "--start-randomization", str(config.get("start_randomization", "none")),
        "--protocol-id", str(config.get("protocol_id", "legacy")),
    ]
    if capture_capacity is not None:
        command.extend(["--capture-capacity", str(capture_capacity)])
    if sampling_protocol and sampling_protocol != "uniform_reservoir_v1":
        command.extend(["--sampling-protocol", sampling_protocol])
    if config.get("method", "original") != "original":
        command.extend(["--method", config["method"]])
    if config.get("policy"):
        command.extend(["--policy", config["policy"]])
    if replan_metrics:
        command.extend(["--metrics", str((run_dir / "replan_metrics.jsonl").resolve())])
    try:
        completed = subprocess.run(command, check=False, pass_fds=() if lock_fd is None else (lock_fd,))
        exit_code = completed.returncode
    except (OSError, subprocess.SubprocessError) as error:
        exit_code = None
        launch_error = str(error)
    else:
        launch_error = None
    result_path = run_dir / "result.json"
    try:
        result = _load_json(result_path) if result_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        result = {}
    rows, summary, capture_error = _capture_rows(run_dir)
    reason = capture_error or launch_error
    health = result.get("simulation_health")
    if isinstance(health, dict) and health.get("valid") is False:
        reason = "invalid_capture: simulation health failed"
    if result.get("instrumentation_error"):
        reason = "invalid_capture: instrumentation write failed"
    if reason is None:
        reason = _validate_capture_rows(rows, summary, result, config, capture_round)
    if not result.get("success", False) and not rows and reason is None:
        reason = result.get("error") or f"runner_failed_exit_{exit_code}"
    capture = result.get("capture") or {}
    entry = {
        "input": {**config, "capture_round": capture_round, "output": str(run_dir)},
        "run_exit": exit_code,
        "success": bool(result.get("success", False)),
        "retained": len(rows),
        "eligible": (summary or {}).get("total_eligible", len(rows)),
        "reject_counts": (summary or {}).get("invalid_reasons", {}),
        "excluded_reason": reason,
        "source_id": capture.get("source_id"),
        "config_id": capture.get("config_id"),
        "artifact_hash": _artifact_hashes(run_dir),
        "sidecars": {
            "result": "result.json" if result_path.is_file() else None,
            "summary": str((run_dir / "instances.jsonl.summary.json").relative_to(run_dir))
            if (run_dir / "instances.jsonl.summary.json").is_file() else None,
        },
        "rows": rows,
    }
    # Valid captures are terminal evidence even when the flight itself failed.
    # Only incomplete or invalid instrumentation is retried on resume.
    if not reason and rows:
        receipt_entry = {key: value for key, value in entry.items() if key != "rows"}
        receipt_entry["result"] = result
        _write_json(receipt, {"schema_version": 1, "identity": identity,
                              "entry": receipt_entry,
                              "artifact_hash": _artifact_hashes(run_dir)})
    return entry


@_with_campaign_lock
def run_campaign(args):
    output = args.output.resolve()
    started_utc = datetime.now(timezone.utc)
    resume = bool(getattr(args, "resume", False))
    if not args.setup_bash.is_file():
        raise ValueError(f"setup bash not found: {args.setup_bash}")
    if args.round and args.split != "train":
        raise ValueError("round 1 and 2 are restricted to training")
    method = getattr(args, "method", "original")
    explicit_role = getattr(args, "collection_role", None)
    role = explicit_role or ("initial" if args.round == 0 else "student_dagger")
    learned_methods = ("bc", "cost", "closed_loop", "set", "objective")
    if role == "initial" and args.round != 0:
        raise ValueError("initial collection role is restricted to round 0")
    if role == "student_dagger" and (args.round == 0 or method not in learned_methods):
        raise ValueError("student_dagger requires a learned method in round 1 or 2")
    if role == "expert_control" and (args.split != "train" or args.round not in (1, 2) or method != "original"):
        raise ValueError("expert_control requires original method on train round 1 or 2")
    if args.round and method == "original" and explicit_role != "expert_control":
        raise ValueError("rounds 1 and 2 original capture requires --collection-role expert_control")
    policy = getattr(args, "policy", None)
    if method in ("bc", "cost", "closed_loop", "set", "objective") and (policy is None or not policy.is_file()):
        raise ValueError("learned capture requires an existing policy file")
    if args.round and method not in ("original", "cost", "closed_loop", "set", "objective"):
        raise ValueError("closed-loop rounds require the current cost-trained policy")
    if args.pilot and method != "original":
        raise ValueError("the initial pilot must use the original planner")
    requested_seeds = getattr(args, "seeds", None)
    if args.pilot and requested_seeds is not None:
        raise ValueError("--seeds cannot be combined with --pilot")
    protocol = getattr(args, "protocol", "legacy")
    families = getattr(args, "scene_families", None)
    if protocol == "benchmark_aligned_v1" and args.pilot:
        raise ValueError("pilot is restricted to the legacy protocol")
    if families and "known_dynamic" in families and protocol != "benchmark_aligned_v1":
        raise ValueError("known_dynamic requires protocol benchmark_aligned_v1")
    output.mkdir(parents=True, exist_ok=True)
    if protocol == "benchmark_aligned_v1":
        selected = _requested_seeds(args.split, requested_seeds)
        configs = aligned_scene_configs(
            args.split, selected, args.counts, families or ("unknown_dynamic", "static_forest"),
        )
        requested_randomization = getattr(args, "start_randomization", None) or "train_box_v1"
        for config in configs:
            config["start_randomization"] = randomization_for_split(
                requested_randomization, args.split
            )
    else:
        configs = scene_configs(args.split, args.counts, args.ratios, requested_seeds)
        if args.pilot:
            if args.split != "train" or args.round != 0:
                raise ValueError("pilot is restricted to train round 0")
            configs = scene_configs("train", [50], [0.65])
        for config in configs:
            config["family"] = "unknown_dynamic"
            config["protocol_id"] = "legacy"
            config["start_randomization"] = "none"
            config["scene_id"] = protocol_scene_id(
                "unknown_dynamic", config["seed"], config["num_obstacles"],
                config["dynamic_ratio"], "legacy",
            )
    for config in configs:
        config["method"] = method
        config["collection_role"] = role
        config["policy"] = str(policy.resolve()) if policy else None
    identity = _campaign_identity(args, configs)
    started_path = output / "started.json"
    if started_path.exists():
        started = _load_json(started_path)
        if started.get("identity") != identity:
            raise ValueError("interrupted campaign identity mismatch")
        first_started_utc = started["created_utc"]
    else:
        first_started_utc = started_utc.isoformat()
        _write_json(started_path, {"created_utc": first_started_utc, "identity": identity})
    if (output / "output.json").is_file():
        manifest = _load_json(output / "output.json")
        if manifest.get("identity") != identity:
            raise ValueError("existing output.json campaign identity mismatch")
        if _manifest_valid(manifest, output):
            return 0
        if manifest.get("completed") and not manifest.get("required_capture_invalid"):
            raise ValueError("completed campaign artifacts changed or are incomplete")
    entries = []
    rows = []
    seen = set()
    duplicate_count = 0
    required_invalid = False
    episode_counts = {}
    capture_capacity = getattr(args, "capture_capacity", None)
    if capture_capacity is not None and not 1 <= int(capture_capacity) <= 20:
        raise ValueError("capture capacity must be between 1 and 20")
    limit = int(capture_capacity) if capture_capacity is not None else (10 if args.round == 0 else 5)
    sampling_protocol = getattr(args, "sampling_protocol", None) or "uniform_reservoir_v1"
    for index, config in enumerate(configs, 1):
        print(f"[campaign] {index}/{len(configs)} seed={config['seed']} n={config['num_obstacles']} ratio={config['dynamic_ratio']}", flush=True)
        entry = _run_config(config, output, args.setup_bash.resolve(), args.round,
                            capture_capacity=capture_capacity, sampling_protocol=sampling_protocol,
                            identity=identity, resume=resume, lock_fd=args.campaign_lock_fd,
                            replan_metrics=bool(getattr(args, "replan_metrics", False)))
        captured_rows = entry.pop("rows")
        if sampling_protocol == "uniform_plus_diverse_v1" and captured_rows:
            captured_rows = select_instances(captured_rows, sampling_protocol, limit)
        if entry["excluded_reason"] and entry["excluded_reason"].startswith(("invalid_capture", "capturemissing")):
            if entry["success"] or entry["excluded_reason"].startswith("invalid_capture"):
                required_invalid = True
            captured_rows = []
        for row in captured_rows:
            key = _row_key(row)
            if None in key or key in seen:
                duplicate_count += 1
                required_invalid = True
                entry["excluded_reason"] = entry.get("excluded_reason") or "duplicate_instance"

                continue
            episode = _episode_key(row)
            if episode_counts.get(episode, 0) >= limit:
                duplicate_count += 1
                required_invalid = True
                entry["excluded_reason"] = entry.get("excluded_reason") or "episode_cap_exceeded"
                continue
            seen.add(key)
            episode_counts[episode] = episode_counts.get(episode, 0) + 1
            rows.append(row)
        if entry["retained"] == 0:
            required_invalid = True
        entries.append(entry)
        print(f"[campaign] retained={entry['retained']} eligible={entry['eligible']} exit={entry['run_exit']}", flush=True)
        if args.pilot and len(rows) >= 100:
            break
    if args.pilot:
        if len(rows) < 100:
            required_invalid = True
        else:
            rows = _pilot_select(rows, 100, 0)
            if len(rows) != 100:
                required_invalid = True
    instances_path = output / "instances.jsonl"
    temporary_instances = instances_path.with_name("instances.jsonl.tmp")
    with temporary_instances.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary_instances, instances_path)
    source_ids = sorted({entry["source_id"] for entry in entries if entry["source_id"]})
    config_ids = sorted({entry["config_id"] for entry in entries if entry["config_id"]})
    reject_counts = {"duplicate_instance": duplicate_count}
    for entry in entries:
        for reason, count in entry["reject_counts"].items():
            reject_counts[reason] = reject_counts.get(reason, 0) + count
        if entry["excluded_reason"]:
            reason = entry["excluded_reason"]
            reject_counts[reason] = reject_counts.get(reason, 0) + 1
    manifest = {
        "schema_version": 1,
        "created_utc": first_started_utc,
        "last_invocation_utc": started_utc.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "requested": {"split": args.split, "round": args.round, "collection_role": role,
                      "counts": [50] if args.pilot else args.counts,
                      "ratios": [0.65] if args.pilot else args.ratios,
                      "seeds": list(SEEDS["train"] if args.pilot else requested_seeds if requested_seeds is not None else SEEDS[args.split]),
                      "pilot": args.pilot,
                      "protocol": getattr(args, "protocol", "legacy"),
                      "scene_families": getattr(args, "scene_families", None),
                      "start_randomization": getattr(args, "start_randomization", None)},
        "all_scene_configs": [{k: v for k, v in entry["input"].items() if k != "output"} for entry in entries],
        "runs": entries,
        "run_exit": [entry["run_exit"] for entry in entries],
        "success": [entry["success"] for entry in entries],
        "retained": len(rows),
        "eligible": sum(entry["eligible"] for entry in entries),
        "reject_counts": reject_counts,
        "input": {"setup_bash": str(args.setup_bash.resolve()), "baseline_runner": str(BASELINE)},
        "artifact_hash": {str(Path(entry["input"]["output"]).relative_to(output)): entry["artifact_hash"] for entry in entries},
        "sidecars": [entry["sidecars"] for entry in entries],
        "source_ids": source_ids,
        "config_ids": config_ids,
        "instances": {"path": "instances.jsonl", "retained": len(rows), "sha256": _sha256(instances_path)["sha256"]},
        "campaign_ran": True,
        "required_capture_invalid": required_invalid,
        "identity": identity,
        "completed": not required_invalid,
    }
    _write_json(output / "output.json", manifest)
    return 2 if required_invalid else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--setup-bash", type=Path, required=True)
    parser.add_argument("--split", choices=tuple(SEEDS), default="train")
    parser.add_argument("--round", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--collection-role", choices=("student_dagger", "expert_control", "initial"))
    parser.add_argument("--counts", nargs="+", type=int, choices=(50, 100, 200), default=[50, 100, 200])
    parser.add_argument("--ratios", nargs="+", type=float, choices=(0.0, 0.65), default=[0.0, 0.65])
    parser.add_argument("--seeds", nargs="+", type=int,
                        help="subset of seeds in the selected split, kept in the requested order")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="resume an interrupted campaign and reuse validated completed runs")
    parser.add_argument("--method", choices=("original", "previous", "bc", "cost", "closed_loop", "set", "objective"), default="original")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--protocol", choices=("legacy", "benchmark_aligned_v1"), default="legacy")
    parser.add_argument("--scene-families", nargs="+", dest="scene_families",
                        choices=("unknown_dynamic", "static_forest", "known_dynamic"))
    parser.add_argument("--start-randomization", choices=("none", "train_box_v1"))
    parser.add_argument("--capture-capacity", type=int, dest="capture_capacity",
                        help="optional per-episode retain cap in 1..20; default remains 10/5 by round")
    parser.add_argument("--sampling-protocol", choices=("uniform_reservoir_v1", "uniform_plus_diverse_v1"),
                        default="uniform_reservoir_v1")
    parser.add_argument("--replan-metrics", action="store_true",
                        help="opt in to per-run replan_metrics.jsonl instrumentation")
    args = parser.parse_args(argv)
    try:
        return run_campaign(args)
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
