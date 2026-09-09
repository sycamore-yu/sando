"""Host-only checks for calibration instrumentation aggregation."""
import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("calibration", ROOT / "scripts/run_capture_worker_calibration.py")
calibration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration)

campaign_spec = importlib.util.spec_from_file_location(
    "campaign", ROOT / "scripts/capture_integer_learning_campaign.py")
campaign = importlib.util.module_from_spec(campaign_spec)
campaign_spec.loader.exec_module(campaign)


def _result(path, samples, success=True, error=None, elapsed=4.0, start=10.0, end=20.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "success": success, "error": error, "elapsed_sec": elapsed,
        "goal_sent_wall_unix": start, "observation_end_wall_unix": end,
        "ground_truth": {"collision": {"min_clearance_samples": samples}},
    }))


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    _result(root / "train/seed30/runs/a/result.json",
            [{"sim_time": 0, "receipt_time": 10}, {"sim_time": 8, "receipt_time": 14}])
    _result(root / "train/seed31/runs/b/result.json",
            [{"sim_time": 4, "receipt_time": 20}, {"sim_time": 3, "receipt_time": 21}],
            success=False, error="observation timeout: goal_reached was not received")
    (root / "train/seed30/runs/a/replan_metrics.jsonl").write_text(
        '{"planning_attempted":true,"success":true,"total_ms":10,"wall_unix_time":12}\n'
        '{"planning_attempted":true,"success":false,"total_ms":30,"wall_unix_time":13}\n')
    (root / "train/seed31/runs/b/replan_metrics.jsonl").write_text(
        '{"planning_attempted":false,"success":false,"total_ms":99,"wall_unix_time":22}\n')
    report = calibration._flight_metrics(root)
    assert report["coverage"]["flights"] == 2
    assert report["coverage"]["expected_flights"] == 2
    assert report["coverage"]["rtf_valid"] == 1
    assert report["coverage"]["metrics_files"] == 2
    assert report["coverage"]["metrics_records"] == 2
    assert report["coverage"]["complete"] is False
    assert report["flights"][0]["rtf"] == 2.0
    assert report["flights"][0]["sample_coverage"] == 1.0
    assert report["flights"][1]["rtf"] is None
    assert report["planning_latency_ms"]["attempted"] == 2
    assert report["planning_latency_ms"]["successful"] == 1
    assert report["planning_latency_ms"]["records_with_latency"] == 2
    assert report["planning_latency_ms"]["mean"] == 20.0
    assert report["planning_latency_ms"]["p50"] == 20.0
    assert report["planning_latency_ms"]["p95"] == 29.0
    assert report["planning_latency_ms"]["p99"] == 29.8
    assert report["planning_latency_ms"]["successful_stats"] == {"count": 1, "p50": 10.0,
                                                                    "p95": 10.0, "p99": 10.0}
    assert report["timeout_rate"] == {"timeouts": 1, "flights": 2, "rate": 0.5}

print("capture calibration metrics tests passed")

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    setup = root / "setup.bash"
    setup.write_text("# fixture\n")
    calls = []
    old_run = campaign.subprocess.run
    campaign.subprocess.run = lambda command, **kwargs: (calls.append(command),
                                                         SimpleNamespace(returncode=2))[1]
    try:
        campaign._run_config({"scene_id": "scene", "seed": 0, "num_obstacles": 50,
                              "dynamic_ratio": 0.65, "split": "train"}, root / "out", setup,
                             0, identity={"test": True}, replan_metrics=True)
    finally:
        campaign.subprocess.run = old_run
    assert calls and calls[0][-2:] == ["--metrics", str((root / "out/runs/scene/replan_metrics.jsonl").resolve())]

print("campaign metrics propagation tests passed")

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    _result(root / "train/seed30/runs/a/result.json",
            [{"sim_time": 0, "receipt_time": 10}, {"sim_time": 0, "receipt_time": 11}],
            start=10.0, end=11.0)
    (root / "train/seed30/runs/a/replan_metrics.jsonl").write_text(
        '{"planning_attempted":true,"success":false,"total_ms":NaN,"wall_unix_time":10.5}\n')
    report = calibration._flight_metrics(root, expected_flights=2)
    assert report["coverage"]["complete"] is False
    assert any("invalid total_ms" in error for error in report["errors"])
    assert any("missing metrics file" in error for error in report["errors"])

print("calibration missing/invalid evidence tests passed")
