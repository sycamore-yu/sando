#!/usr/bin/env python3
"""Host-only checks for qualified and wall-clock throughput accounting."""

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/measure_integer_throughput.py"
spec = importlib.util.spec_from_file_location("throughput", SCRIPT)
throughput = importlib.util.module_from_spec(spec)
spec.loader.exec_module(throughput)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    seed = root / "train" / "seed0"
    run = seed / "runs" / "scene"
    run.mkdir(parents=True)
    (seed / "output.json").write_text(json.dumps({
        "completed": True, "required_capture_invalid": False,
        "created_utc": "2026-01-01T00:00:00+00:00",
        "completed_utc": "2026-01-01T00:00:02+00:00",
    }))
    (run / "result.json").write_text(json.dumps({"success": True, "elapsed_sec": 10}))
    (run / "instances.jsonl.summary.json").write_text(json.dumps({"retained": 4, "total_eligible": 5}))
    (seed / "runs" / "attempts").mkdir()
    seed2 = root / "train" / "seed1"
    run2 = seed2 / "runs" / "scene2"
    run2.mkdir(parents=True)
    (seed2 / "output.json").write_text(json.dumps({
        "completed": True, "required_capture_invalid": False,
        "created_utc": "2026-01-01T00:00:05+00:00",
        "completed_utc": "2026-01-01T00:00:07+00:00",
    }))
    (run2 / "result.json").write_text(json.dumps({"success": True, "elapsed_sec": 10}))
    (run2 / "instances.jsonl.summary.json").write_text(json.dumps({"retained": 2, "total_eligible": 2}))
    report = throughput.measure_root(root)
    assert report["qualified_retained_instances"] == 6
    assert report["sum_flight_hours"] == 20 / 3600
    assert report["wall_interval_sec"] == 7
    assert report["union_wall_interval_sec"] == 4
    assert report["instances_per_wall_hour"] == 6 / (7 / 3600)

print("PASS: throughput excludes incomplete attempts and reports wall versus summed flight time")

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    specs = ((0, 10, 1, 2), (5, 8, 2, 3), (20, 25, 4, 1))
    for index, (start, end, elapsed, retained) in enumerate(specs):
        seed = root / "train" / f"seed{index}"; run = seed / "runs" / "scene"; run.mkdir(parents=True)
        (seed / "output.json").write_text(json.dumps({"completed": True, "required_capture_invalid": False,
            "created_utc": f"2026-01-01T00:00:{start:02d}+00:00", "completed_utc": f"2026-01-01T00:00:{end:02d}+00:00"}))
        (run / "result.json").write_text(json.dumps({"success": True, "elapsed_sec": elapsed}))
        (run / "instances.jsonl.summary.json").write_text(json.dumps({"retained": retained, "total_eligible": retained}))
    report = throughput.measure_root(root)
    assert report["qualified_retained_instances"] == 6
    assert report["wall_interval_sec"] == 25
    assert report["union_wall_interval_sec"] == 15
    assert report["sum_flight_hours"] == 7 / 3600
print("PASS: throughput handles overlapping intervals, gaps, and resumed campaign wall bounds")
