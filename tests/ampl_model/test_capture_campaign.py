#!/usr/bin/env python3
"""Host-only campaign orchestration checks; no simulation command is run."""

import importlib.util
import json
import tempfile
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/capture_integer_learning_campaign.py"
spec = importlib.util.spec_from_file_location("campaign", SCRIPT)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


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

    def fake_run(command, check=False):
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

    def failed_run(command, check=False):
        run_dir = Path(command[command.index("--output") + 1])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(json.dumps({"success": False, "error": "launch failed"}))
        return Completed()

    campaign.subprocess.run = failed_run
    assert campaign.run_campaign(failed_args) == 0
    failed_manifest = json.loads((failed_args.output / "output.json").read_text())
    assert failed_manifest["retained"] == 0
    assert all(run["excluded_reason"] for run in failed_manifest["runs"])

    subset_args = Namespace(output=root / "subset", setup_bash=setup, split="train", round=0,
                            counts=[50], ratios=[0.65], seeds=[3, 1], pilot=False)
    assert campaign.run_campaign(subset_args) == 0
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

    def aligned_run(command, check=False):
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

    def capacity_run(command, check=False):
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
