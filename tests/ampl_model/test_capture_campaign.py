#!/usr/bin/env python3
"""Host-only campaign orchestration checks; no simulation command is run."""

import importlib.util
import json
import multiprocessing
import os
import tempfile
import time
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/capture_integer_learning_campaign.py"
spec = importlib.util.spec_from_file_location("campaign", SCRIPT)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
campaign._runtime_identity = lambda args: {"test_runtime": True}


def _locked_probe(args):
    return campaign._acquire_lock(args.output)


def _hold_lock(path, ready):
    handle = campaign._acquire_lock(path)
    ready.set()
    time.sleep(1)
    handle.close()


def test_campaign_lock_releases_after_exception_and_blocks_concurrently():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "campaign"
        decorated = campaign._with_campaign_lock(lambda args: (_ for _ in ()).throw(RuntimeError("boom")))
        try:
            decorated(Namespace(output=output, resume=False))
        except RuntimeError as error:
            assert str(error) == "boom"
        else:
            raise AssertionError("exception did not propagate")
        handle = campaign._acquire_lock(output); handle.close()
        ctx = multiprocessing.get_context("fork")
        ready = ctx.Event(); holder = ctx.Process(target=_hold_lock, args=(output, ready)); holder.start()
        assert ready.wait(5)
        try:
            try:
                campaign._acquire_lock(output)
            except ValueError as error:
                assert "locked" in str(error)
            else:
                raise AssertionError("concurrent campaign lock acquisition succeeded")
        finally:
            holder.join(5)
            assert not holder.is_alive()


def test_manifest_rejects_missing_aggregate_instances():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "campaign"; output.mkdir()
        manifest = {"completed": True, "required_capture_invalid": False, "runs": [], "artifact_hash": {}}
        (output / "output.json").write_text(json.dumps(manifest))
        assert campaign._manifest_valid(manifest, output) is False


def _direct_config():
    return {"scene_id": "scene", "seed": 0, "num_obstacles": 50,
            "dynamic_ratio": 0.65, "split": "train", "method": "original",
            "policy": None, "family": "unknown_dynamic", "protocol_id": "legacy",
            "start_randomization": "none"}


def _write_fake_capture(run_dir, success=False, health=None):
    row = {"schema_version": 1, "scene_id": "scene", "episode_id": "ep",
           "request_id": "0", "factor_id": "0", "source_id": "src", "config_id": "cfg",
           "outcome": {"capture": {"split": "train", "capture_round": 0}}}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "instances.jsonl").write_text(json.dumps(row) + "\n")
    (run_dir / "instances.jsonl.summary.json").write_text(json.dumps({"total_eligible": 1, "invalid_reasons": {}, "metadata": {"scene_id": "scene", "source_id": "src", "config_id": "cfg"}}))
    result = {"success": success, "error": "flight failed", "capture": {"source_id": "src", "config_id": "cfg"}}
    if health is not None: result["simulation_health"] = health
    (run_dir / "result.json").write_text(json.dumps(result))


def test_failed_flight_with_valid_rows_is_terminal_and_reused():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); setup = root / "setup"; setup.write_text("# test\n")
        calls = []
        class Completed: returncode = 0
        def fake_run(command, check=False, **kwargs):
            calls.append(command); _write_fake_capture(Path(command[command.index("--output") + 1]), success=False); return Completed()
        old = campaign.subprocess.run; campaign.subprocess.run = fake_run
        try:
            config = _direct_config(); identity = {"runtime": "test"}
            first = campaign._run_config(config, root / "out", setup, 0, identity=identity)
            assert first["retained"] == 1 and first["excluded_reason"] is None
            second = campaign._run_config(config, root / "out", setup, 0, identity=identity, resume=True)
            assert second["retained"] == 1 and len(calls) == 1
        finally:
            campaign.subprocess.run = old


def test_partial_run_is_quarantined_and_retried_and_corruption_rejected():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); setup = root / "setup"; setup.write_text("# test\n"); output = root / "out"
        config = _direct_config(); run_dir = output / "runs" / "scene"; run_dir.mkdir(parents=True); (run_dir / "partial").write_text("x")
        class Completed: returncode = 0
        old = campaign.subprocess.run
        campaign.subprocess.run = lambda command, check=False, **kwargs: (_write_fake_capture(Path(command[command.index("--output") + 1]), success=True), Completed())[1]
        try:
            entry = campaign._run_config(config, output, setup, 0, identity={"runtime": "test"}, resume=True)
            assert entry["retained"] == 1 and list((output / "attempts").iterdir())
            (run_dir / "instances.jsonl").write_text("corrupt\n")
            try:
                campaign._run_config(config, output, setup, 0, identity={"runtime": "test"}, resume=True)
            except ValueError as error:
                assert "corrupted" in str(error) or "invalid" in str(error)
            else:
                raise AssertionError("corrupted completed run was accepted")
        finally:
            campaign.subprocess.run = old


def test_started_identity_time_survives_interrupted_resume():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); setup = root / "setup"; setup.write_text("# test\n")
        output = root / "out"
        args = Namespace(output=output, setup_bash=setup, split="train", round=0,
                         counts=[50], ratios=[0.65], seeds=[0], pilot=False, resume=False)
        old = campaign.subprocess.run
        campaign.subprocess.run = lambda command, check=False, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt())
        try:
            try:
                campaign.run_campaign(args)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("interrupted campaign did not propagate")
            started = json.loads((output / "started.json").read_text())
            args.resume = True
            campaign.subprocess.run = lambda command, check=False, **kwargs: (_write_fake_capture(Path(command[command.index("--output") + 1]), success=True), type("Completed", (), {"returncode": 0})())[1]
            campaign.run_campaign(args)
            assert json.loads((output / "started.json").read_text())["created_utc"] == started["created_utc"]
        finally:
            campaign.subprocess.run = old


def test_invalid_simulation_health_excludes_retained_rows():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); setup = root / "setup"; setup.write_text("# test\n")
        old = campaign.subprocess.run
        campaign.subprocess.run = lambda command, check=False, **kwargs: (_write_fake_capture(Path(command[command.index("--output") + 1]), health={"valid": False, "reason": "gazebo crash"}), type("Completed", (), {"returncode": 0})())[1]
        try:
            entry = campaign._run_config(_direct_config(), root / "out", setup, 0, identity={"runtime": "test"})
            assert entry["retained"] == 1 and entry["excluded_reason"] == "invalid_capture: simulation health failed"
        finally:
            campaign.subprocess.run = old


assert set(campaign.SEEDS["train"]).isdisjoint(campaign.SEEDS["validation"])
assert set(campaign.SEEDS["validation"]).isdisjoint(campaign.SEEDS["test"])
assert campaign.scene_configs("train", [50], [0.65])[0]["seed"] == 0
assert campaign.scene_configs("validation", [50], [0.65])[0]["seed"] == 100
assert [row["seed"] for row in campaign.scene_configs("train", [50], [0.65], [3, 1])] == [3, 1]
for seeds, message in (([], "at least one"), ([1, 1], "duplicates"), ([100], "outside")):
    try:
        campaign.scene_configs("train", [50], [0.65], seeds)
    except ValueError as error:
        assert message in str(error)
    else:
        raise AssertionError(f"invalid seed selection accepted: {seeds}")

rows = [{"scene_id": "s", "episode_id": "old", "request_id": str(i), "factor_id": str(i)} for i in range(4)]
rows += [{"scene_id": "s", "episode_id": "last", "request_id": str(i), "factor_id": str(i)} for i in range(20)]
selected = campaign._pilot_select(rows, target=10, seed=0)
assert len(selected) == 10 and selected[:4] == rows[:4]
assert selected[4:] == campaign._pilot_select(rows, target=10, seed=0)[4:]
assert len({campaign._row_key(row) for row in selected}) == 10

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    setup = root / "setup.bash"
    setup.write_text("# test\n")
    calls = []

    class Completed:
        returncode = 0

    def fake_run(command, check=False, **kwargs):
        calls.append(command)
        run_dir = Path(command[command.index("--output") + 1])
        seed = int(command[command.index("--seed") + 1])
        run_dir.mkdir(parents=True, exist_ok=True)
        capture_round = int(command[command.index("--capture-round") + 1])
        entries = []
        for i in range(10):
            entries.append({"schema_version": 1, "scene_id": f"n50-d0.65-seed{seed}",
                            "episode_id": f"ep-{seed}-r{capture_round}", "request_id": str(i),
                            "factor_id": str(i), "source_id": "src", "config_id": "cfg",
                            "outcome": {"capture": {"split": "train", "capture_round": capture_round}}})
        (run_dir / "instances.jsonl").write_text("".join(json.dumps(row) + "\n" for row in entries))
        (run_dir / "instances.jsonl.summary.json").write_text(json.dumps({
            "total_eligible": 10, "invalid_reasons": {},
            "metadata": {"scene_id": f"n50-d0.65-seed{seed}", "source_id": "src", "config_id": "cfg"},
        }))
        (run_dir / "result.json").write_text(json.dumps({"success": True, "capture": {"source_id": "src", "config_id": "cfg"}}))
        return Completed()

    campaign.subprocess.run = fake_run
    args = Namespace(output=root / "campaign", setup_bash=setup, split="train", round=0,
                     counts=[50], ratios=[0.65], pilot=True)
    assert campaign.run_campaign(args) == 0
    assert len(calls) == 10  # exactly enough ten-row episodes for the pilot target.
    manifest = json.loads((args.output / "output.json").read_text())
    assert manifest["retained"] == 100 and manifest["eligible"] == 100
    assert manifest["source_ids"] == ["src"] and manifest["config_ids"] == ["cfg"]
    assert len((args.output / "instances.jsonl").read_text().splitlines()) == 100
    pilot_manifest = manifest["requested"]
    assert pilot_manifest["seeds"] == list(range(40))

    failed_args = Namespace(output=root / "failed", setup_bash=setup, split="validation", round=0,
                            counts=[50], ratios=[0.0], pilot=False)

    def failed_run(command, check=False, **kwargs):
        run_dir = Path(command[command.index("--output") + 1])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(json.dumps({"success": False, "error": "launch failed"}))
        return Completed()

    campaign.subprocess.run = failed_run
    assert campaign.run_campaign(failed_args) == 2
    failed_manifest = json.loads((failed_args.output / "output.json").read_text())
    assert failed_manifest["retained"] == 0
    assert all(run["excluded_reason"] for run in failed_manifest["runs"])

    subset_args = Namespace(output=root / "subset", setup_bash=setup, split="train", round=0,
                            counts=[50], ratios=[0.65], seeds=[3, 1], pilot=False)
    assert campaign.run_campaign(subset_args) == 2
    subset_manifest = json.loads((subset_args.output / "output.json").read_text())
    assert subset_manifest["requested"]["seeds"] == [3, 1]
    assert [item["seed"] for item in subset_manifest["all_scene_configs"]] == [3, 1]
    assert len(subset_manifest["runs"]) == 2

    bad_round = Namespace(output=root / "bad-round", setup_bash=setup, split="validation", round=1,
                         counts=[50], ratios=[0.0], pilot=False)
    try:
        campaign.run_campaign(bad_round)
    except ValueError as error:
        assert "restricted" in str(error)
    else:
        raise AssertionError("validation round 1 was accepted")

    pilot_with_seeds = Namespace(output=root / "pilot-with-seeds", setup_bash=setup, split="train", round=0,
                                 counts=[50], ratios=[0.65], seeds=[1], pilot=True)
    try:
        campaign.run_campaign(pilot_with_seeds)
    except ValueError as error:
        assert "--seeds" in str(error) and "--pilot" in str(error)
    else:
        raise AssertionError("--seeds with --pilot was accepted")

    insufficient = Namespace(output=root / "insufficient", setup_bash=setup, split="train", round=0,
                             counts=[50], ratios=[0.65], pilot=True)
    assert campaign.run_campaign(insufficient) == 2
    partial = json.loads((insufficient.output / "output.json").read_text())
    assert partial["campaign_ran"] and partial["retained"] == 0

    aligned_calls = []

    def aligned_run(command, check=False, **kwargs):
        aligned_calls.append(command)
        run_dir = Path(command[command.index("--output") + 1])
        family = command[command.index("--scene-family") + 1]
        scene = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=True)
        row = {"schema_version": 1, "scene_id": scene, "episode_id": f"{scene}:capture:r0",
               "request_id": "0", "factor_id": "0", "source_id": "src", "config_id": "cfg",
               "outcome": {"capture": {"split": "train", "capture_round": 0}}}
        (run_dir / "instances.jsonl").write_text(json.dumps(row) + "\n")
        (run_dir / "instances.jsonl.summary.json").write_text(json.dumps({
            "total_eligible": 1, "invalid_reasons": {},
            "metadata": {"scene_id": scene, "source_id": "src", "config_id": "cfg"},
        }))
        (run_dir / "result.json").write_text(json.dumps({"success": True, "capture": {"source_id": "src", "config_id": "cfg"}}))
        assert "train_box_v1" in command
        assert family in ("unknown_dynamic", "static_forest")
        return Completed()

    campaign.subprocess.run = aligned_run
    aligned_args = Namespace(output=root / "aligned", setup_bash=setup, split="train", round=0,
                             counts=[50, 100, 200], ratios=[0.0, 0.65], seeds=[0],
                             pilot=False, protocol="benchmark_aligned_v1",
                             scene_families=None, start_randomization=None)
    assert campaign.run_campaign(aligned_args) == 0
    aligned_manifest = json.loads((aligned_args.output / "output.json").read_text())
    families = {item["family"] for item in aligned_manifest["all_scene_configs"]}
    assert families == {"unknown_dynamic", "static_forest"}
    assert len(aligned_calls) == 6
    assert all(item["start_randomization"] == "train_box_v1" for item in aligned_manifest["all_scene_configs"])
    assert all("--capture-capacity" not in command for command in aligned_calls)

    capacity_calls = []

    def capacity_run(command, check=False, **kwargs):
        # Legacy capacity path is not train_box_v1; do not reuse aligned_run asserts.
        capacity_calls.append(command)
        run_dir = Path(command[command.index("--output") + 1])
        scene = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=True)
        row = {"schema_version": 1, "scene_id": scene, "episode_id": f"{scene}:capture:r0",
               "request_id": "0", "factor_id": "0", "source_id": "src", "config_id": "cfg",
               "outcome": {"capture": {"split": "train", "capture_round": 0}}}
        (run_dir / "instances.jsonl").write_text(json.dumps(row) + "\n")
        (run_dir / "instances.jsonl.summary.json").write_text(json.dumps({
            "total_eligible": 1, "invalid_reasons": {},
            "metadata": {"scene_id": scene, "source_id": "src", "config_id": "cfg"},
        }))
        (run_dir / "result.json").write_text(json.dumps({"success": True, "capture": {"source_id": "src", "config_id": "cfg"}}))
        return Completed()

    campaign.subprocess.run = capacity_run
    capacity_args = Namespace(output=root / "capacity20", setup_bash=setup, split="train", round=0,
                              counts=[50], ratios=[0.65], seeds=[0], pilot=False,
                              protocol="legacy", capture_capacity=20,
                              sampling_protocol="uniform_plus_diverse_v1")
    assert campaign.run_campaign(capacity_args) == 0
    assert any("--capture-capacity" in command and "20" in command for command in capacity_calls)
    assert any("--sampling-protocol" in command and "uniform_plus_diverse_v1" in command
               for command in capacity_calls)

print("PASS: campaign split/round validation, deterministic pilot subset, duplicate-safe manifest, failure accounting")
test_campaign_lock_releases_after_exception_and_blocks_concurrently()
test_manifest_rejects_missing_aggregate_instances()
test_failed_flight_with_valid_rows_is_terminal_and_reused()
test_partial_run_is_quarantined_and_retried_and_corruption_rejected()
test_started_identity_time_survives_interrupted_resume()
test_invalid_simulation_health_excludes_retained_rows()


def _role_args(output, setup, role=None, resume=False):
    values = dict(output=output, setup_bash=setup, split="train", round=1,
                  counts=[50], ratios=[0.65], seeds=[0], pilot=False,
                  protocol="legacy", capture_capacity=5, sampling_protocol="uniform_reservoir_v1",
                  method="original", policy=None, resume=resume)
    if role is not None:
        values["collection_role"] = role
    return Namespace(**values)


def test_collection_roles_round_one_contract():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); setup = root / "setup.bash"; setup.write_text("# test\n")
        for args in (_role_args(root / "implicit", setup), _role_args(root / "initial", setup, "initial"),
                     _role_args(root / "student", setup, "student_dagger")):
            try:
                campaign.run_campaign(args)
            except ValueError as error:
                assert "expert_control" in str(error) or "initial" in str(error) or "student_dagger" in str(error)
            else:
                raise AssertionError("inconsistent round-one collection role accepted")

        def successful_run(command, check=False, **kwargs):
            run_dir = Path(command[command.index("--output") + 1]); run_dir.mkdir(parents=True, exist_ok=True)
            row = {"schema_version": 1, "scene_id": "n50-d0.65-seed0", "episode_id": "ep",
                   "request_id": "r", "factor_id": "f", "source_id": "src", "config_id": "cfg",
                   "outcome": {"capture": {"split": "train", "capture_round": 1}}}
            (run_dir / "instances.jsonl").write_text(json.dumps(row) + "\n")
            (run_dir / "instances.jsonl.summary.json").write_text(json.dumps({"total_eligible": 1, "invalid_reasons": {}, "metadata": {"scene_id": "n50-d0.65-seed0", "source_id": "src", "config_id": "cfg"}}))
            (run_dir / "result.json").write_text(json.dumps({"success": True, "capture": {"source_id": "src", "config_id": "cfg"}}))
            return Namespace(returncode=0)
        campaign.subprocess.run = successful_run
        control = _role_args(root / "control", setup, "expert_control")
        assert campaign.run_campaign(control) == 0
        manifest = json.loads((control.output / "output.json").read_text())
        assert manifest["identity"]["collection_role"] == "expert_control"
        try:
            started = json.loads((control.output / "started.json").read_text())
            started["identity"]["collection_role"] = "student_dagger"
            (control.output / "started.json").write_text(json.dumps(started))
            campaign.run_campaign(_role_args(control.output, setup, "expert_control", resume=True))
        except ValueError as error:
            assert "student_dagger" in str(error) or "identity" in str(error)
        else:
            raise AssertionError("resume with changed collection role accepted")


test_collection_roles_round_one_contract()
