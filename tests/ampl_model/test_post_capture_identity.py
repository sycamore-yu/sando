#!/usr/bin/env python3
"""Standalone model reuse identity checks for post capture workflow."""
import copy
import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import run_aligned_post_capture as workflow


def model_fixture(directory):
    root = Path(directory)
    out = root / "model"
    out.mkdir()
    train, validation = root / "train.jsonl", root / "validation.jsonl"
    train.write_text('{"instance": {"scene_id": "train"}}\n')
    validation.write_text('{"instance": {"scene_id": "validation"}}\n')
    model = out / "model.json"
    model.write_text('{"schema_version": 1}\n')
    completed = {"status": "complete", "method": "bc", "seed": 0,
                 "epochs": 100, "completed_epochs": 100, "batch_size": 32,
                 "learning_rate": 1e-3, "threads": 4, "device": "cpu",
                 "new_data_sha256": None,
                 "new_data_sampling": {"enabled": False, "ratio": "50/50", "batch_size": 32},
                 "train_data_sha256": workflow.file_sha256(train),
                 "validation_data_sha256": workflow.file_sha256(validation),
                 "training_script_sha256": workflow.file_sha256(workflow.SCRIPTS / "train_integer_corridor_policy.py"),
                 "training_batch_sha256": workflow.file_sha256(workflow.SCRIPTS / "integer_corridor_training_batch.py"),
                 "policy_source_sha256": workflow.file_sha256(workflow.SCRIPTS / "integer_corridor_policy.py"),
                 "set_supervision_sha256": workflow.file_sha256(workflow.SCRIPTS / "integer_set_supervision.py"),
                 "supervision_config": workflow.CONFIG,
                 "dependencies": workflow.training_dependencies(),
                 "model_sha256": workflow.file_sha256(model)}
    (out / "completed.json").write_text(json.dumps(completed) + "\n")
    return out, train, validation


def test_valid_model_reuse():
    with tempfile.TemporaryDirectory() as directory:
        out, train, validation = model_fixture(directory)
        assert workflow.validate_model_reuse(out, train, validation, "bc", 0)["status"] == "complete"


def test_changed_identity_fields_and_artifacts_are_rejected():
    fields = ("method", "seed", "device", "training_script_sha256", "training_batch_sha256", "policy_source_sha256", "set_supervision_sha256", "supervision_config", "model_sha256", "dependencies")
    with tempfile.TemporaryDirectory() as directory:
        out, train, validation = model_fixture(directory)
        completed_path = out / "completed.json"
        baseline = json.loads(completed_path.read_text())
        for field in fields:
            changed = copy.deepcopy(baseline)
            changed[field] = ("changed" if isinstance(changed[field], str) else {"changed": True})
            completed_path.write_text(json.dumps(changed) + "\n")
            try:
                workflow.validate_model_reuse(out, train, validation, "bc", 0)
            except RuntimeError as error:
                assert "stale model output" in str(error)
            else:
                raise AssertionError(f"changed {field} was accepted")
        completed_path.write_text(json.dumps(baseline) + "\n")
        train.write_text(train.read_text() + "changed\n")
        try:
            workflow.validate_model_reuse(out, train, validation, "bc", 0)
        except RuntimeError:
            pass
        else:
            raise AssertionError("changed train data was accepted")
        train.write_text('{"instance": {"scene_id": "train"}}\n')
        model = out / "model.json"
        model.write_text(model.read_text() + "changed\n")
        try:
            workflow.validate_model_reuse(out, train, validation, "bc", 0)
        except RuntimeError:
            pass
        else:
            raise AssertionError("changed model artifact was accepted")


def main():
    test_valid_model_reuse()
    test_changed_identity_fields_and_artifacts_are_rejected()
    print("post capture identity tests passed")


if __name__ == "__main__":
    main()
