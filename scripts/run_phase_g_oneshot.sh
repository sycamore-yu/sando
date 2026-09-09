#!/usr/bin/env bash
# Phase G: one-shot online 1T + frozen corridor-cost Z + real C(T) + 1 QP.
# Usage: TIMING=<model.json> SEEDS="200" bash scripts/run_phase_g_oneshot.sh
set -o pipefail
ROOT_REPO="${ROOT_REPO:-/root/sando_ws/src/sando}"
source "${ROOT_REPO}/docker/dev_env.sh"
export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-${ROOT_REPO}/docker/gurobi.lic}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-91}"
export ROS_LOCALHOST_ONLY=1
# one-shot: do NOT set SANDO_CORRIDOR_CANDIDATE_LIMIT (C++ auto=1 when proposal_count==1)

TIMING="${TIMING:-${ROOT_REPO}/prototypes/time_fixed_z_qp/evidence/phase_e_train/timing_kkt_lam0.1_seed0.json}"
POLICY="${POLICY:-${ROOT_REPO}/docker/dev-workspace/results/joint-time-v2/models/corridor-cost.json}"
SETUP_BASH="${SETUP_BASH:-/root/sando_ws/install-dev/setup.bash}"
OUT_ROOT="${OUT_ROOT:-${ROOT_REPO}/docker/dev-workspace/results/request-latency-v3/online/phase_g_$(date +%Y%m%d_%H%M%S)}"
SEEDS="${SEEDS:-200}"
SCENE_FAMILY="${SCENE_FAMILY:-static_forest}"
NUM_OBSTACLES="${NUM_OBSTACLES:-50}"
DYNAMIC_RATIO="${DYNAMIC_RATIO:-0.0}"

mkdir -p "$OUT_ROOT"
{
  echo "OUT_ROOT=$OUT_ROOT"
  echo "TIMING=$TIMING"
  echo "POLICY=$POLICY"
  echo "HEAD=$(git -C "$ROOT_REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "SEEDS=$SEEDS"
} | tee "$OUT_ROOT/out_path.txt"

for SEED in $SEEDS; do
  tmux has-session -t sando_sim 2>/dev/null && tmux kill-session -t sando_sim || true
  sleep 1
  OUT="$OUT_ROOT/seed${SEED}"
  mkdir -p "$OUT"
  set +e
  python3 "${ROOT_REPO}/scripts/integer_learning_baseline_sim.py" \
    --setup-bash "$SETUP_BASH" \
    --output "$OUT/run" \
    --metrics "$OUT/metrics.jsonl" \
    --method cost \
    --policy "$POLICY" \
    --timing-policy "$TIMING" \
    --timing-nfe 1 \
    --seed "$SEED" \
    --scene-family "$SCENE_FAMILY" \
    --num-obstacles "$NUM_OBSTACLES" \
    --dynamic-ratio "$DYNAMIC_RATIO" \
    --protocol-id benchmark_aligned_v1 \
    --start-randomization none \
    2>&1 | tee "$OUT/driver.log"
  RC=${PIPESTATUS[0]}
  set -e
  echo "SEED=${SEED} RC=${RC}" | tee -a "$OUT_ROOT/out_path.txt"
  python3 - "$OUT" "$SEED" <<'PY'
import json, sys
from pathlib import Path
from collections import Counter
out = Path(sys.argv[1])
seed = int(sys.argv[2])
rows = []
if (out / "metrics.jsonl").exists():
    rows = [json.loads(l) for l in (out / "metrics.jsonl").open() if l.strip()]
pa = [r for r in rows if r.get("planning_attempted")]
publish = [r for r in rows if r.get("kind") == "publish"]
ctrl = [r for r in rows if r.get("kind") == "controller_first_use"]
oneshot = 0
fallback = 0
for r in pa:
    if r.get("append_success") and r.get("fallback") is False:
        oneshot += 1
    if r.get("append_success") and r.get("fallback") is True:
        fallback += 1
res = {}
if (out / "run" / "result.json").exists():
    res = json.loads((out / "run" / "result.json").read_text())
summary = {
    "seed": seed,
    "n_attempted": len(pa),
    "append_ok": sum(1 for r in pa if r.get("append_success")),
    "oneshot_append_no_fallback": oneshot,
    "fallback_append": fallback,
    "publish_events": len(publish),
    "controller_first_use_events": len(ctrl),
    "failure_stage": dict(Counter(str(r.get("failure_stage")) for r in pa)),
    "goal_reached": res.get("goal_reached"),
    "success": res.get("success"),
    "goal_distance_m": res.get("goal_distance_m"),
    "error": res.get("error"),
}
(out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY
done

python3 - "$OUT_ROOT" "$TIMING" "$POLICY" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
subs = [json.loads(p.read_text()) for p in sorted(root.glob("seed*/summary.json"))]
out = {
    "schema_version": 1,
    "kind": "phase_g_oneshot",
    "timing_policy": sys.argv[2],
    "corridor_policy": sys.argv[3],
    "runs": subs,
}
(root / "summary.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
PY
echo PHASE_G_DONE
