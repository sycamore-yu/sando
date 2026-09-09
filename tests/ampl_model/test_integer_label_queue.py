#!/usr/bin/env python3
"""Standalone regression tests for the integer labeling queue."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import integer_label_queue as queue


def data_root(directory, records, run_name="run"):
    root = Path(directory) / "data"
    run = root / "train" / "seed0" / "runs" / run_name
    run.mkdir(parents=True)
    (root / "train" / "seed0" / "output.json").write_text("{}\n")
    (run / "instances.jsonl").write_text("".join(json.dumps(item) + "\n" for item in records))
    (run / "result.json").write_text("{}\n")
    return root


def copier(directory):
    path = Path(directory) / "labeler.py"
    path.write_text("#!/usr/bin/env python3\nimport argparse, shutil\np=argparse.ArgumentParser(); p.add_argument('--input'); p.add_argument('--output'); a=p.parse_args(); shutil.copyfile(a.input, a.output)\n")
    path.chmod(0o755)
    return path


def one_task(directory):
    records = [{"scene_id": "scene", "episode_id": "episode", "request_id": "1", "factor_id": "0"}]
    root = data_root(directory, records)
    queue_dir = Path(directory) / "queue"
    assert queue.enqueue(root, queue_dir)["enqueued"]
    return root, queue_dir, next((queue_dir / "pending").glob("*.json"))


def test_raw_planning_instance_round_trip():
    with tempfile.TemporaryDirectory() as directory:
        _, queue_dir, _ = one_task(directory)
        assert queue.worker_loop(queue_dir, Path(directory) / "work", copier(directory), "worker", once=True) == 1
        merged = Path(directory) / "merged.jsonl"
        assert queue.merge(queue_dir, merged)["done"] == 1
        assert json.loads(merged.read_text()) == {"scene_id": "scene", "episode_id": "episode", "request_id": "1", "factor_id": "0"}


def test_source_hash_change_rejected():
    with tempfile.TemporaryDirectory() as directory:
        _, queue_dir, pending = one_task(directory)
        source = Path(json.loads(pending.read_text())["instances"])
        source.write_text(source.read_text() + "\n")
        try:
            queue.run_labeler(json.loads(pending.read_text()), Path(directory) / "work", copier(directory))
        except RuntimeError as error:
            assert "changed after enqueue" in str(error)
        else:
            raise AssertionError("changed source snapshot was accepted")


def test_claim_replace_interruption_keeps_owner_metadata():
    with tempfile.TemporaryDirectory() as directory:
        _, queue_dir, pending = one_task(directory)
        original_replace = queue.os.replace
        def fail_claim_replace(source, destination):
            if Path(destination).parent == queue_dir / "claimed":
                raise OSError("simulated interruption")
            return original_replace(source, destination)
        queue.os.replace = fail_claim_replace
        try:
            try:
                queue.claim(queue_dir, "worker")
            except OSError as error:
                assert "simulated interruption" in str(error)
            else:
                raise AssertionError("claim interruption did not propagate")
        finally:
            queue.os.replace = original_replace
        owner = json.loads(pending.read_text())
        assert owner["worker"] == "worker" and owner["claim_token"]
        assert queue.claim(queue_dir, "worker") is not None


def test_merge_rejects_missing_inventory_state():
    with tempfile.TemporaryDirectory() as directory:
        _, queue_dir, pending = one_task(directory)
        pending.unlink()
        try:
            queue.merge(queue_dir, Path(directory) / "merged.jsonl")
        except RuntimeError as error:
            assert "inventory" in str(error)
        else:
            raise AssertionError("merge accepted task missing from all states")


def test_failed_labeler_cannot_merge_without_partial():
    with tempfile.TemporaryDirectory() as directory:
        _, queue_dir, _ = one_task(directory)
        bad = Path(directory) / "bad.py"
        bad.write_text("#!/usr/bin/env python3\nraise SystemExit(7)\n")
        bad.chmod(0o755)
        assert queue.worker_loop(queue_dir, Path(directory) / "work", bad, "worker", once=True) == -1
        try:
            queue.merge(queue_dir, Path(directory) / "merged.jsonl")
        except RuntimeError as error:
            assert "failed=1" in str(error)
        else:
            raise AssertionError("incomplete queue was merged")


def main():
    for test in (test_raw_planning_instance_round_trip, test_source_hash_change_rejected, test_claim_replace_interruption_keeps_owner_metadata, test_merge_rejects_missing_inventory_state, test_failed_labeler_cannot_merge_without_partial):
        test()
    print("integer label queue tests passed")


if __name__ == "__main__":
    main()
