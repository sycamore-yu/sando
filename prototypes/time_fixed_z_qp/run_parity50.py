#!/usr/bin/env python3
"""Phase 4: C++ Gurobi fixed-Z vs Python Clarabel Diff-QP forward parity on ≥50 instances.

Host genesis Python runs Clarabel; Gurobi probe runs inside sando-dev via docker exec.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

from run_time_qp import build_spec, solve_hard_qp
from train_time_nn_qp import instance_from_pack_item

FACTORS_EXTRA = (1.0, 1.5, 2.0)
REPO_IN_DOCKER = "/root/sando_ws/src/sando"
PROBE_IN_DOCKER = "/root/sando_ws/build-dev/sando/fixed_z_parity_probe"


def close_scaled(a, b, tol=1e-4):
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def fixture_from_item(item):
    inst = dict(item["instance"])
    inst.setdefault("t0", 0.0)
    inst.setdefault("norm", "Linf")
    inst.setdefault("planner", "SANDO")
    return inst


def python_row(qp, assignment, factor):
    hard = solve_hard_qp(build_spec(qp, factor), assignment)
    if "jerk" not in hard:
        return {"factor": factor, "ok": False, "error": hard.get("status", "python_fail")}
    return {
        "factor": factor,
        "ok": True,
        "objective_jerk": float(hard["jerk"]),
        "status": hard.get("status"),
    }


def run_cpp_docker(fixture_host: Path, assignment, factors, repo_host: Path):
    rel = fixture_host.resolve().relative_to(repo_host.resolve())
    fixture_docker = f"{REPO_IN_DOCKER}/{rel.as_posix()}"
    z = ",".join(str(int(v)) for v in assignment)
    f = ",".join(str(float(v)) for v in factors)
    cmd = (
        "source /root/sando_ws/src/sando/docker/dev_env.sh && "
        f"{PROBE_IN_DOCKER} {fixture_docker} {z} {f}"
    )
    completed = subprocess.run(
        ["docker", "exec", "sando-dev", "bash", "-lc", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "stderr": (completed.stderr or "")[-2000:],
            "stdout": (completed.stdout or "")[-2000:],
        }
    lines = [ln for ln in completed.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        return {"ok": False, "stderr": "no json", "stdout": completed.stdout[-2000:]}
    return json.loads(lines[-1])


def compare_item(item, fixtures_dir: Path, repo_host: Path):
    qp = instance_from_pack_item(item)
    assignment = [int(v) for v in item["assignment"]]
    factors = sorted({float(item["factor_capture"]), *FACTORS_EXTRA})
    fixture_path = fixtures_dir / f"{item['scene_id']}_{item['request_id']}.json"
    fixture_path.write_text(json.dumps(fixture_from_item(item)))

    py_rows = {f: python_row(qp, assignment, f) for f in factors}
    cpp = run_cpp_docker(fixture_path, assignment, factors, repo_host)
    if not cpp.get("rows"):
        return {
            "scene_id": item["scene_id"],
            "request_id": item["request_id"],
            "ok": False,
            "reason": "cpp_failed",
            "cpp": {k: cpp.get(k) for k in ("stderr", "status") if k in cpp},
        }

    pairs = []
    all_ok = True
    for crow in cpp["rows"]:
        f = float(crow["factor"])
        prow = py_rows.get(f) or python_row(qp, assignment, f)
        status_match = bool(crow.get("ok")) == bool(prow.get("ok"))
        obj_ok = None
        rel = None
        if crow.get("ok") and prow.get("ok"):
            cpp_obj = float(crow["objective"])
            py_obj = float(prow["objective_jerk"])
            obj_ok = close_scaled(cpp_obj, py_obj)
            rel = abs(cpp_obj - py_obj) / max(1.0, abs(py_obj))
            if not obj_ok:
                all_ok = False
        elif not status_match:
            all_ok = False
        pairs.append(
            {
                "factor": f,
                "cpp_ok": crow.get("ok"),
                "py_ok": prow.get("ok"),
                "status_match": status_match,
                "cpp_objective": crow.get("objective"),
                "py_jerk": prow.get("objective_jerk"),
                "objective_close": obj_ok,
                "objective_rel_err": rel,
                "residuals_valid": (crow.get("residuals") or {}).get("valid"),
            }
        )
    return {
        "scene_id": item["scene_id"],
        "request_id": item["request_id"],
        "assignment": assignment,
        "ok": all_ok,
        "pairs": pairs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("evidence/parity50_pack.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/phase4_parity50.json"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    pack = json.loads(args.pack.read_text())
    items = pack["items"]
    if args.limit:
        items = items[: args.limit]

    fixtures_dir = args.pack.parent / "_parity_fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in items:
        rows.append(compare_item(item, fixtures_dir, args.repo))
        print(
            json.dumps(
                {
                    "done": len(rows),
                    "last_ok": rows[-1]["ok"],
                    "scene": rows[-1]["scene_id"],
                }
            ),
            flush=True,
        )

    n_ok = sum(1 for r in rows if r.get("ok"))
    # feasible-pair objective stats
    rels = []
    for r in rows:
        for p in r.get("pairs") or []:
            if p.get("objective_rel_err") is not None:
                rels.append(p["objective_rel_err"])
    summary = {
        "schema_version": 1,
        "kind": "phase4_qp_forward_parity",
        "n": len(rows),
        "n_ok": n_ok,
        "pass_rate": n_ok / max(len(rows), 1),
        "objective_rel_err_max": max(rels) if rels else None,
        "objective_rel_err_median": sorted(rels)[len(rels) // 2] if rels else None,
        "pack": str(args.pack),
        "rows": rows,
    }
    args.out.write_text(json.dumps(summary, indent=2))
    print(
        json.dumps(
            {k: summary[k] for k in ("n", "n_ok", "pass_rate", "objective_rel_err_max", "objective_rel_err_median")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
