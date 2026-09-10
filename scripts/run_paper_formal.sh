#!/usr/bin/env bash
# Paper formal closed-loop matrix (plan2 Phase 7–8).
# Defaults: procedural_static easy (unknown_dynamic d=0 n=50), frozen λ=1.0 DiffOpt.
# Usage:
#   GROUP=procedural_static_easy SEEDS="1000" METHODS="original supervised true_diff" \
#     bash scripts/run_paper_formal.sh
set -o pipefail
ROOT_REPO="${ROOT_REPO:-/root/sando_ws/src/sando}"
GROUP="${GROUP:-procedural_static_easy}"

# Map group → launch knobs (matches docs/paper-study-v2/environment_manifest.json)
case "$GROUP" in
  procedural_static_easy)
    export SCENE_FAMILY=unknown_dynamic NUM_OBSTACLES=50 DYNAMIC_RATIO=0.0
    export SEEDS="${SEEDS:-$(seq 1000 1029 | tr '\n' ' ')}"
    ;;
  procedural_static_medium)
    export SCENE_FAMILY=unknown_dynamic NUM_OBSTACLES=100 DYNAMIC_RATIO=0.0
    export SEEDS="${SEEDS:-$(seq 1100 1129 | tr '\n' ' ')}"
    ;;
  procedural_static_hard)
    export SCENE_FAMILY=unknown_dynamic NUM_OBSTACLES=200 DYNAMIC_RATIO=0.0
    export SEEDS="${SEEDS:-$(seq 1200 1229 | tr '\n' ' ')}"
    ;;
  unknown_dynamic_easy)
    export SCENE_FAMILY=unknown_dynamic NUM_OBSTACLES=50 DYNAMIC_RATIO=0.65
    export SEEDS="${SEEDS:-$(seq 2000 2029 | tr '\n' ' ')}"
    ;;
  unknown_dynamic_medium)
    export SCENE_FAMILY=unknown_dynamic NUM_OBSTACLES=100 DYNAMIC_RATIO=0.65
    export SEEDS="${SEEDS:-$(seq 2100 2129 | tr '\n' ' ')}"
    ;;
  legacy_static_forest_easy_repeat)
    export SCENE_FAMILY=static_forest NUM_OBSTACLES=50 DYNAMIC_RATIO=0.0
    export SEEDS="${SEEDS:-$(seq 200 229 | tr '\n' ' ')}"
    ;;
  *)
    echo "unknown GROUP=$GROUP" >&2
    exit 2
    ;;
esac

export METHODS="${METHODS:-original supervised true_diff}"
export TRUE_DIFF="${TRUE_DIFF:-${ROOT_REPO}/prototypes/time_fixed_z_qp/evidence/phase_e_train/timing_kkt_lam1.0_seed0.json}"
export SUPERVISED="${SUPERVISED:-${ROOT_REPO}/docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json}"
export POLICY="${POLICY:-${ROOT_REPO}/docker/dev-workspace/results/joint-time-v2/models/corridor-cost.json}"
export OUT_ROOT="${OUT_ROOT:-${ROOT_REPO}/docker/dev-workspace/results/request-latency-v3/online/paper_${GROUP}_$(date +%Y%m%d_%H%M%S)}"

echo "GROUP=$GROUP SCENE_FAMILY=$SCENE_FAMILY n=$NUM_OBSTACLES d=$DYNAMIC_RATIO"
echo "SEEDS=$SEEDS METHODS=$METHODS"
echo "TRUE_DIFF=$TRUE_DIFF"
echo "OUT_ROOT=$OUT_ROOT"
mkdir -p "$OUT_ROOT"
cp -f "${ROOT_REPO}/docs/paper-study-v2/FREEZE.json" "$OUT_ROOT/FREEZE.json" 2>/dev/null || true
echo "$GROUP" > "$OUT_ROOT/group.txt"

bash "${ROOT_REPO}/scripts/run_phase_k_pilots.sh"
