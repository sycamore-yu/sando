#!/usr/bin/env bash
# Phase K fair online pilots: Original / supervised / true-diff (and optional FD).
# Usage:
#   METHODS="supervised true_diff" SEEDS="200 201 202" bash scripts/run_phase_k_pilots.sh
set -o pipefail
ROOT_REPO="${ROOT_REPO:-/root/sando_ws/src/sando}"
source "${ROOT_REPO}/docker/dev_env.sh"
export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-${ROOT_REPO}/docker/gurobi.lic}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-94}"
export ROS_LOCALHOST_ONLY=1

SETUP_BASH="${SETUP_BASH:-/root/sando_ws/install-dev/setup.bash}"
POLICY="${POLICY:-${ROOT_REPO}/docker/dev-workspace/results/joint-time-v2/models/corridor-cost.json}"
SUPERVISED="${SUPERVISED:-${ROOT_REPO}/docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json}"
TRUE_DIFF="${TRUE_DIFF:-${ROOT_REPO}/prototypes/time_fixed_z_qp/evidence/phase_f_train/timing_kkt_lam0.1_seed0.json}"
FD_PROXY="${FD_PROXY:-${ROOT_REPO}/prototypes/time_fixed_z_qp/evidence/phase_e_train/timing_fd_lam0.0_seed0.json}"
OUT_ROOT="${OUT_ROOT:-${ROOT_REPO}/docker/dev-workspace/results/request-latency-v3/online/phase_k_$(date +%Y%m%d_%H%M%S)}"
SEEDS="${SEEDS:-200 201 202 203 204 205}"
METHODS="${METHODS:-supervised true_diff}"
SCENE_FAMILY="${SCENE_FAMILY:-static_forest}"
NUM_OBSTACLES="${NUM_OBSTACLES:-50}"
DYNAMIC_RATIO="${DYNAMIC_RATIO:-0.0}"

mkdir -p "$OUT_ROOT"
{
  echo "OUT_ROOT=$OUT_ROOT"
  echo "METHODS=$METHODS"
  echo "SEEDS=$SEEDS"
  echo "TRUE_DIFF=$TRUE_DIFF"
  echo "HEAD=$(git -C "$ROOT_REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
} | tee "$OUT_ROOT/out_path.txt"

run_one() {
  local method="$1" seed="$2"
  local out="$OUT_ROOT/${method}/seed${seed}"
  mkdir -p "$out"
  # Resume-safe: skip completed paired runs (paper formal matrices).
  if [[ -f "$out/run/result.json" && -f "$out/summary.json" ]]; then
    echo "SKIP_COMPLETE METHOD=${method} SEED=${seed}" | tee -a "$OUT_ROOT/out_path.txt"
    return 0
  fi
  tmux has-session -t sando_sim 2>/dev/null && tmux kill-session -t sando_sim || true
  # Orphan gzserver blocks odom readiness on later seeds.
  for pid in $(ps -eo pid,cmd | grep '[g]zserver' | grep -v defunct | awk '{print $1}'); do
    kill -9 "$pid" 2>/dev/null || true
  done
  sleep 2
  local args=(
    --setup-bash "$SETUP_BASH"
    --output "$out/run"
    --metrics "$out/metrics.jsonl"
    --seed "$seed"
    --scene-family "$SCENE_FAMILY"
    --num-obstacles "$NUM_OBSTACLES"
    --dynamic-ratio "$DYNAMIC_RATIO"
    --protocol-id benchmark_aligned_v1
    --start-randomization none
  )
  case "$method" in
    original)
      args+=(--method original)
      ;;
    supervised)
      args+=(--method cost --policy "$POLICY" --timing-policy "$SUPERVISED" --timing-nfe 1)
      ;;
    true_diff)
      args+=(--method cost --policy "$POLICY" --timing-policy "$TRUE_DIFF" --timing-nfe 1)
      ;;
    fd_proxy)
      args+=(--method cost --policy "$POLICY" --timing-policy "$FD_PROXY" --timing-nfe 1)
      ;;
    *)
      echo "unknown method $method" >&2
      return 2
      ;;
  esac
  set +e
  python3 "${ROOT_REPO}/scripts/integer_learning_baseline_sim.py" "${args[@]}" 2>&1 | tee "$out/driver.log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "METHOD=${method} SEED=${seed} RC=${rc}" | tee -a "$OUT_ROOT/out_path.txt"
  python3 - "$out" "$method" "$seed" <<'PY'
import json, sys
from pathlib import Path
from collections import Counter
out, method, seed = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
rows = [json.loads(l) for l in (out/"metrics.jsonl").open() if l.strip()] if (out/"metrics.jsonl").exists() else []
pa = [r for r in rows if r.get("planning_attempted")]
ctrl = [r for r in rows if r.get("kind") == "controller_first_use"]
oneshot = sum(1 for r in pa if r.get("append_success") and r.get("fallback") is False)
fb = sum(1 for r in pa if r.get("append_success") and r.get("fallback") is True)
res = json.loads((out/"run"/"result.json").read_text()) if (out/"run"/"result.json").exists() else {}
totals = [r.get("total_ms") for r in pa if isinstance(r.get("total_ms"), (int, float))]
totals_sorted = sorted(totals)
def pct(p):
    if not totals_sorted: return None
    i = min(len(totals_sorted)-1, int(round((p/100.0)*(len(totals_sorted)-1))))
    return totals_sorted[i]
summary = {
    "method": method, "seed": seed,
    "n_attempted": len(pa),
    "append_ok": sum(1 for r in pa if r.get("append_success")),
    "oneshot_append_no_fallback": oneshot,
    "fallback_append": fb,
    "controller_first_use_events": len(ctrl),
    "failure_stage": dict(Counter(str(r.get("failure_stage")) for r in pa)),
    "latency_p50_ms": pct(50), "latency_p95_ms": pct(95),
    "goal_reached": res.get("goal_reached"), "success": res.get("success"),
    "goal_distance_m": res.get("goal_distance_m"), "error": res.get("error"),
    "wall_elapsed_sec": res.get("wall_elapsed_sec"),
}
(out/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
print(json.dumps(summary, indent=2))
PY
}

for method in $METHODS; do
  for seed in $SEEDS; do
    run_one "$method" "$seed" || true
  done
done

python3 - "$OUT_ROOT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
runs = [json.loads(p.read_text()) for p in sorted(root.glob("*/*/summary.json"))]
out = {"schema_version": 1, "kind": "phase_k_pilots", "runs": runs}
(root/"summary.json").write_text(json.dumps(out, indent=2)+"\n")
print(json.dumps({"n_runs": len(runs)}, indent=2))
PY
echo PHASE_K_DONE
