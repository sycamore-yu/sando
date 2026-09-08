#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import integer_label_queue as queue


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "data"
        run = root / "train" / "seed0" / "runs" / "unknown_dynamic-n50-d0.65-seed0"
        run.mkdir(parents=True)
        (root / "train" / "seed0" / "output.json").write_text("{}\n")
        instances = run / "instances.jsonl"
        instances.write_text(json.dumps({"instance": {"scene_id": "unknown_dynamic-n50-d0.65-seed0",
                                                      "episode_id": "e", "request_id": "1", "factor_id": "0"}}) + "\n")
        (run / "instances.jsonl.summary.json").write_text(json.dumps({"retained": 1}) + "\n")
        (run / "result.json").write_text(json.dumps({"success": True}) + "\n")
        queue_dir = Path(directory) / "queue"
        work = Path(directory) / "work"
        report = queue.enqueue(root, queue_dir)
        assert len(report["enqueued"]) == 1
        first = queue.sha256_file(instances)
        instances.write_text(instances.read_text() + "\n")
        labeler = Path(directory) / "fake_labeler.py"
        labeler.write_text("#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nPath(sys.argv[4]).write_text(Path(sys.argv[2]).read_text())\n")
        os.chmod(labeler, 0o755)
        pending_files = sorted((queue_dir / "pending").glob("*.json"))
        assert pending_files
        try:
            queue.run_labeler(json.loads(pending_files[0].read_text()), work, labeler)
        except RuntimeError as error:
            assert "changed after enqueue" in str(error)
        else:
            raise AssertionError("changed snapshot accepted")
        instances.write_bytes(bytes.fromhex("") if False else bytes())
        # restore original bytes via fingerprint by rewriting original line
        instances.write_text(json.dumps({"instance": {"scene_id": "unknown_dynamic-n50-d0.65-seed0",
                                                      "episode_id": "e", "request_id": "1", "factor_id": "0"}}) + "\n")
        assert queue.sha256_file(instances) == first
        processed = queue.worker_loop(queue_dir, work, labeler, "w0", once=True)
        assert processed == 1
        merged = Path(directory) / "merged.jsonl"
        counts = queue.merge(queue_dir, merged)
        assert counts["done"] == 1
        assert merged.read_text().count("\n") == 1
        # interrupt resume: nothing pending remains
        assert queue.worker_loop(queue_dir, work, labeler, "w0", once=True) == 0
    print("integer label queue tests passed")


if __name__ == "__main__":
    main()
