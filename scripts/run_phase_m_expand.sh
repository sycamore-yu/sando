#!/usr/bin/env bash
# Phase M formal expand: frozen λ=1.0 true-diff vs supervised on seeds 200-229.
set -o pipefail
ROOT_REPO="${ROOT_REPO:-/root/sando_ws/src/sando}"
source "${ROOT_REPO}/docker/dev_env.sh"
export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-${ROOT_REPO}/docker/gurobi.lic}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-110}"
export ROS_LOCALHOST_ONLY=1
export METHODS="${METHODS:-supervised true_diff}"
export SEEDS="${SEEDS:-$(seq 200 229 | tr '\n' ' ')}"
export TRUE_DIFF="${TRUE_DIFF:-${ROOT_REPO}/prototypes/time_fixed_z_qp/evidence/phase_e_train/timing_kkt_lam1.0_seed0.json}"
export OUT_ROOT="${OUT_ROOT:-${ROOT_REPO}/docker/dev-workspace/results/request-latency-v3/online/phase_m_expand_200_229}"
export SCENE_FAMILY="${SCENE_FAMILY:-static_forest}"
export DYNAMIC_RATIO="${DYNAMIC_RATIO:-0.0}"
export NUM_OBSTACLES="${NUM_OBSTACLES:-50}"
mkdir -p "$OUT_ROOT"
cp -f "${ROOT_REPO}/docs/final-study/FREEZE.json" "$OUT_ROOT/FREEZE.json" 2>/dev/null || true
bash "${ROOT_REPO}/scripts/run_phase_k_pilots.sh"
echo PHASE_M_EXPAND_DONE
