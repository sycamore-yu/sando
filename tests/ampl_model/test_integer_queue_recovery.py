#!/usr/bin/env python3
"""Crash and ownership regressions for integer_label_queue."""
import json
import multiprocessing
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import integer_label_queue as queue


def fixture(directory):
    root = Path(directory) / "data"
    run = root / "train" / "seed0" / "runs" / "r"
    run.mkdir(parents=True)
    (root / "train" / "seed0" / "output.json").write_text("{}\n")
    (run / "instances.jsonl").write_text(json.dumps({"scene_id": "s", "episode_id": "e", "request_id": "1", "factor_id": "0"}) + "\n")
    (run / "result.json").write_text("{}\n")
    qdir = Path(directory) / "queue"
    queue.enqueue(root, qdir)
    return qdir


def sleeping_labeler(directory):
    path = Path(directory) / "sleep.py"
    path.write_text("#!/usr/bin/env python3\nimport os, time\nfrom pathlib import Path\nPath(os.environ['PID_FILE']).write_text(str(os.getpid()))\nwhile True: time.sleep(1)\n")
    path.chmod(0o755)
    return path


def worker_process(qdir, work, labeler, worker):
    queue.worker_loop(qdir, work, labeler, worker, once=True)


def merge_process(qdir, output):
    queue.merge(qdir, output)


def wait_for_pid(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return int(path.read_text())
        time.sleep(0.02)
    raise AssertionError("fake solver did not start")


def test_crash_before_owner_prep_leaves_clean_pending():
    with tempfile.TemporaryDirectory() as directory:
        qdir = fixture(directory)
        pending = next((qdir / "pending").glob("*.json"))
        original_atomic = queue.atomic_json
        def fail_owner(path, value):
            if Path(path) == pending:
                raise OSError("simulated pre-owner crash")
            return original_atomic(path, value)
        queue.atomic_json = fail_owner
        try:
            try:
                queue.claim(qdir, "worker")
            except OSError as error:
                assert "pre-owner" in str(error)
            else:
                raise AssertionError("pre-owner interruption did not propagate")
        finally:
            queue.atomic_json = original_atomic
        record = json.loads(pending.read_text())
        assert "claim_token" not in record and not (qdir / "claimed" / pending.name).exists()


def test_pid_reuse_metadata_does_not_override_live_lock():
    with tempfile.TemporaryDirectory() as directory:
        qdir = fixture(directory)
        task = queue.claim(qdir, "worker")
        claimed = qdir / "claimed" / task["claim_file"]
        record = json.loads(claimed.read_text())
        record["pid"] = 1
        claimed.write_text(json.dumps(record))
        assert queue.recover(qdir, "worker", task["id"]) == 0
        assert claimed.exists()
        queue.publish(qdir, {"task": task, "returncode": 1, "output": None})


def test_orphan_solver_lock_blocks_recovery_until_solver_exit():
    with tempfile.TemporaryDirectory() as directory:
        qdir = fixture(directory)
        pid_file = Path(directory) / "solver.pid"
        os.environ["PID_FILE"] = str(pid_file)
        ctx = multiprocessing.get_context("spawn")
        worker = ctx.Process(target=worker_process, args=(qdir, Path(directory) / "work", sleeping_labeler(directory), "worker"))
        solver_pid = None
        try:
            worker.start()
            solver_pid = wait_for_pid(pid_file)
            worker.terminate()
            worker.join(5)
            assert not worker.is_alive()
            assert queue.recover(qdir, "worker") == 0
            os.kill(solver_pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if queue.recover(qdir, "worker") == 1:
                    break
                time.sleep(0.02)
            else:
                raise AssertionError("recovery did not proceed after solver exit")
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            if solver_pid is None:
                solver_pid = int(pid_file.read_text()) if pid_file.exists() else None
            if solver_pid is None:
                pass
            else:
                try:
                    os.kill(solver_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            os.environ.pop("PID_FILE", None)


def test_concurrent_merge_is_atomic_and_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        qdir = fixture(directory)
        labeler = Path(directory) / "copy.py"
        labeler.write_text("#!/usr/bin/env python3\nimport argparse, shutil\np=argparse.ArgumentParser(); p.add_argument('--input'); p.add_argument('--output'); a=p.parse_args(); shutil.copyfile(a.input,a.output)\n")
        labeler.chmod(0o755)
        queue.worker_loop(qdir, Path(directory) / "work", labeler, "worker", once=True)
        output = Path(directory) / "merged.jsonl"
        ctx = multiprocessing.get_context("spawn")
        processes = [ctx.Process(target=merge_process, args=(qdir, output)) for _ in range(3)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            assert process.exitcode == 0
        assert output.read_text().count("\n") == 1


def main():
    for test in (test_crash_before_owner_prep_leaves_clean_pending, test_pid_reuse_metadata_does_not_override_live_lock, test_orphan_solver_lock_blocks_recovery_until_solver_exit, test_concurrent_merge_is_atomic_and_idempotent):
        test()
    print("integer queue recovery tests passed")


if __name__ == "__main__":
    main()
