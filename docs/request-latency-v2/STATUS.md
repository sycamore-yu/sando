# Request latency stages 6–8 status (Part 2)

Assumptions: mid-technical reader; Part1 owns training/queryer, Part2 owns measurement.

Git tip when written: see branch `feat/ampl-gurobi` on `personal`.
Evidence corpus (gitignored): `docker/dev-workspace/results/request-latency-v2/`.

## Progress

| Stage | Status | Notes |
|-------|--------|-------|
| 6 timing + 12 replay + compile-skip | **done** | usable/reclaim/publish fields; update-path skip unused AMPL compile |
| 6 expand ≥60 | **done** | selected60 formal k=1; final accept 0.75; first-pass bc/cost 0.667/0.700 (see stage6-first-vs-fallback) |
| 6 hypotheses §3.5 | **done** | `docs/request-latency-v2/stage6-hypotheses.md` |
| 6 first vs fallback | **done** | `stage6-first-vs-fallback.md`; results in `request-latency-v3/analysis/` |
| 6 geometry §3.6 | **partial→proxy done** | forest cylinder proxy on odom: `stage6-forest-cylinder-proxy.md`; event-time align still blocked |
| 7 same-budget 4 arms | **partial** | fixed_time + assign_only; time_only/joint blocked without multi-T rebuild |
| 7 candidate-limit=1 in replay | **done** | `--candidate-limit`; matched n=5 accept 100%; bc/cost p95 ~64ms vs original ~105ms |
| code: verify+prev-overflow+recreate | **done** | see `request-latency-v3/analysis/code_fixes.md` |
| fresh vs persistent reuse | **done** | `--runtime-reuse`; selected12 k=1 ~3.9x wall; accept 120/120; see `fresh-vs-persistent.md` |
| online 4-scene timing | **partial** | protocol frozen; install-dev smoke no-motion; campaign pending healthy binary |
| Part1 §5 checklist | **done** | `PART1_INTERFACE_CHECKLIST.md` |
| 8 backfill list | **done** | `stage8/backfill_list.json` |
| 8 queryer coverage | **done (same-f only)** | same-factor OK; new-f blocked — see `stage8-queryer-coverage.md` |
| 8 new model verify | **blocked** | no new Part1 model id |

## Problems

1. Validation capture had `metrics:null` → no online `cancel_drain` / multi-factor critical path for selected IDs.
2. Offline replay ≠ online parallel wall clock; do not equate.
3. Reconstructable new-factor queries blocked: missing `visible_map`, `global_path`, `v_max/a_max/j_max` on old snapshots.
4. Part1 joint dual-head trained weights not published → structure contrast / stage8 model verify blocked.
5. Mid-build `dev-build` exit 71 if sources change during compile (race); rebuild after edits settle.
6. **install-dev online flight**: candidate_limit=1 OK in metrics, but robot no motion / observation timeout — bisect vs frozen install + Part1 WIP.

## Recovery

```bash
make -C docker dev-status
source docker/dev_env.sh   # inside sando-dev
make -C docker dev-build
# replay example:
replay_integer_planning --input …/selected12.jsonl --output out.jsonl \
  --bc …/bc.json --cost …/cost.json --seed 101 --candidate-limit 1 \
  --runtime-reuse fresh   # or persistent
```

## Next

1. Rebuild + stage7 matched arms with `--candidate-limit 1`.
2. Part1: fill observation fields or re-capture reconstructable snapshots; publish new model sha256.
3. Part2: re-run four arms + stage8 verify; selected60 first/fallback split done — next is matched arms / Part1 models.
