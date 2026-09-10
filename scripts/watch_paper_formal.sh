#!/usr/bin/env bash
# Resume-safe formal matrix watcher: wait for ALL_GROUPS_DONE, else resume; then aggregate.
set -euo pipefail
ROOT="${ROOT:-/home/tong/tongworkspace/dockerworkplace/sando}"
ONLINE="$ROOT/docker/dev-workspace/results/request-latency-v3/online"
LOG="$ONLINE/paper_formal_driver.log"
MARKER="$ROOT/docs/paper-study-v2/FORMAL_COMPLETE.json"
POLL_SEC="${POLL_SEC:-120}"

resume_driver() {
  echo "RESUME $(date -Is)" | tee -a "$LOG"
  docker exec -d sando-dev bash -lc "
    set -e
    source /root/sando_ws/src/sando/docker/dev_env.sh
    cd /root/sando_ws/src/sando
    LOG=/root/sando_ws/src/sando/docker/dev-workspace/results/request-latency-v3/online/paper_formal_driver.log
    {
      echo RESUME_START \$(date -Is)
      for GROUP in procedural_static_easy unknown_dynamic_easy procedural_static_medium; do
        echo \"==== GROUP \$GROUP \$(date -Is) ====\"
        export GROUP
        export METHODS='original supervised true_diff'
        unset SEEDS
        export OUT_ROOT=/root/sando_ws/src/sando/docker/dev-workspace/results/request-latency-v3/online/paper_\${GROUP}
        bash scripts/run_paper_formal.sh || echo \"GROUP_FAIL \$GROUP\"
      done
      echo ALL_GROUPS_DONE \$(date -Is)
    } >> \"\$LOG\" 2>&1
  "
}

aggregate() {
  python3 "$ROOT/scripts/aggregate_paper_formal.py" \
    "$ONLINE/paper_procedural_static_easy" \
    "$ONLINE/paper_unknown_dynamic_easy" \
    "$ONLINE/paper_procedural_static_medium" \
    --out "$ROOT/docs/paper-study-v2/FORMAL_AGGREGATE.json"
  python3 "$ROOT/scripts/attribute_paper_failures.py" \
    "$ONLINE/paper_procedural_static_easy" \
    "$ONLINE/paper_unknown_dynamic_easy" \
    "$ONLINE/paper_procedural_static_medium" \
    --out "$ROOT/docs/paper-study-v2/FAILURE_ATTRIBUTION.json"
  python3 "$ROOT/scripts/paired_bootstrap_paper.py" \
    --aggregate "$ROOT/docs/paper-study-v2/FORMAL_AGGREGATE.json" \
    --out "$ROOT/docs/paper-study-v2/PAIRED_BOOTSTRAP.json"
  python3 "$ROOT/scripts/write_paper_tables.py" \
    --aggregate "$ROOT/docs/paper-study-v2/FORMAL_AGGREGATE.json" \
    --out-dir "$ROOT/docs/paper-study-v2/final"
  python3 - <<PY
import json, subprocess, time
from pathlib import Path
root = Path("$ROOT")
agg = json.loads((root/"docs/paper-study-v2/FORMAL_AGGREGATE.json").read_text())
n = sum(g.get("n_rows", 0) for g in agg.get("groups", {}).values())
sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
payload = {
  "schema_version": 1,
  "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
  "commit": sha,
  "n_rows": n,
  "expected_rows": 270,
  "aggregate": "docs/paper-study-v2/FORMAL_AGGREGATE.json",
  "attribution": "docs/paper-study-v2/FAILURE_ATTRIBUTION.json",
  "bootstrap": "docs/paper-study-v2/PAIRED_BOOTSTRAP.json",
  "tables": "docs/paper-study-v2/final/",
}
(root/"docs/paper-study-v2/FORMAL_COMPLETE.json").write_text(json.dumps(payload, indent=2)+"\n")
print(json.dumps(payload, indent=2))
PY
}

count_done() {
  find "$ONLINE"/paper_procedural_static_easy "$ONLINE"/paper_unknown_dynamic_easy "$ONLINE"/paper_procedural_static_medium \
    -path '*/seed*/run/result.json' 2>/dev/null | wc -l
}

runner_alive() {
  docker exec sando-dev bash -lc 'ps -eo cmd | grep -E "run_paper_formal|run_phase_k_pilots|integer_learning_baseline_sim" | grep -v grep' >/dev/null 2>&1
}

echo "watch start $(date -Is) done=$(count_done)/270"
while true; do
  if grep -q 'ALL_GROUPS_DONE' "$LOG" 2>/dev/null; then
    echo "detected ALL_GROUPS_DONE"
    break
  fi
  done_n=$(count_done)
  if ! runner_alive; then
    echo "runner dead at done=$done_n; resume with skip-complete $(date -Is)"
    resume_driver
    sleep 30
  else
    echo "alive done=$done_n/270 $(date -Is)"
  fi
  sleep "$POLL_SEC"
done

aggregate
echo "watch complete $(date -Is)"
