"""Host-only checks; this does not exercise AMPLS or certify a flight."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/capture_integer_learning_baseline.py"
spec = importlib.util.spec_from_file_location("baseline", SCRIPT)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)

with tempfile.TemporaryDirectory() as directory:
    repo = Path(directory)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "config.yaml").write_text("num_N: 5\n")
    subprocess.run(["git", "add", "config.yaml"], cwd=repo, check=True)
    # No daemon or license needed: explicitly simulate unavailable probes.
    baseline.probe = lambda args, root: {"command": args, "returncode": 1}
    first = baseline.capture(repo, "unused")
    second = baseline.capture(repo, "unused")
    assert first["tracked_content_sha256"] == second["tracked_content_sha256"]
    assert not first["acceptance"]["sampling_allowed"]
    (repo / "config.yaml").write_text("num_N: 6\n")
    assert baseline.capture(repo, "unused")["tracked_content_sha256"] != first["tracked_content_sha256"]
    (repo / "config.yaml").unlink()
    assert baseline.capture(repo, "unused")["tracked_files"]["config.yaml"]["missing"]
    output = repo / "baseline.json"
    output.write_text(json.dumps(first))
    before = output.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "already exists" in result.stderr
    assert output.read_bytes() == before

print("PASS: stable identity, edits/deletions detected, gate remains closed, overwrite refused")
