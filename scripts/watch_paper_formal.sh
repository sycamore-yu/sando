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
  python3 "$ROOT/scripts/fill_paper_rq.py" --root "$ROOT/docs/paper-study-v2"
  # Copy FAILURE_ANALYSIS into final/
  if [[ -f "$ROOT/docs/paper-study-v2/FAILURE_ATTRIBUTION.json" ]]; then
    python3 - <<PY
import json
from pathlib import Path
root = Path("$ROOT/docs/paper-study-v2")
attr = json.loads((root/"FAILURE_ATTRIBUTION.json").read_text())
text = ["# FAILURE_ANALYSIS", "", "Source: FAILURE_ATTRIBUTION.json", "",
        f"- wrong_Z_count_learned: {attr.get('wrong_Z_count_learned')}",
        f"- non_success_count: {attr.get('non_success_count')}",
        f"- restart_Z_learning: {attr.get('restart_Z_learning')}", "",
        "Per-group counts:", ""]
for g in attr.get("groups") or []:
    text.append(f"## {g.get('group')}")
    text.append("")
    for k,v in sorted((g.get("counts") or {}).items()):
        text.append(f"- {k}: {v}")
    text.append("")
(root/"final"/"FAILURE_ANALYSIS.md").write_text("\n".join(text)+"\n")
print("wrote final/FAILURE_ANALYSIS.md")
PY
  fi
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
  local n=0
  for d in "$ONLINE"/paper_procedural_static_easy "$ONLINE"/paper_unknown_dynamic_easy "$ONLINE"/paper_procedural_static_medium; do
    [[ -d "$d" ]] || continue
    n=$((n + $(find "$d" -path '*/seed*/run/result.json' 2>/dev/null | wc -l)))
  done
  echo "$n"
  return 0
}

runner_alive() {
  docker exec sando-dev bash -lc 'ps -eo cmd | grep -E "run_paper_formal|run_phase_k_pilots|integer_learning_baseline_sim" | grep -v grep' >/dev/null 2>&1 || return 1
  return 0
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
