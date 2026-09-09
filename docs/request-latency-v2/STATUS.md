# Request latency stages 6–8 status (Part 2)

Assumptions: mid-technical reader; Part1 owns training/queryer, Part2 owns measurement.

Git tip when written: see branch `feat/ampl-gurobi` on `personal`.
Evidence corpus (gitignored): `docker/dev-workspace/results/request-latency-v2/`.

## Progress

| Stage | Status | Notes |
|-------|--------|-------|
| 6 timing + 12 replay + compile-skip | **done** | usable/reclaim/publish fields; update-path skip unused AMPL compile |
| 6 expand ≥60 | **done** | `selection/selected60_manifest.json` (results tree) |
| 6 hypotheses §3.5 | **done** | `docs/request-latency-v2/stage6-hypotheses.md` |
| 6 geometry §3.6 | **partial** | AABB cases documented; cylinder recompute blocked |
| 7 same-budget 4 arms | **partial** | fixed_time + assign_only; time_only/joint blocked without multi-T rebuild |
| 7 candidate-limit=1 in replay | **done** | `--candidate-limit`; matched n=5 accept 100%; bc/cost p95 ~64ms vs original ~105ms |
| 8 backfill list | **done** | `stage8/backfill_list.json` |
| 8 queryer coverage | **done (same-f only)** | same-factor OK; new-f blocked — see `stage8-queryer-coverage.md` |
| 8 new model verify | **blocked** | no new Part1 model id |

## Problems

1. Validation capture had `metrics:null` → no online `cancel_drain` / multi-factor critical path for selected IDs.
2. Offline replay ≠ online parallel wall clock; do not equate.
3. Reconstructable new-factor queries blocked: missing `visible_map`, `global_path`, `v_max/a_max/j_max` on old snapshots.
4. Part1 joint dual-head trained weights not published → structure contrast / stage8 model verify blocked.
5. Mid-build `dev-build` exit 71 if sources change during compile (race); rebuild after edits settle.

## Recovery

```bash
make -C docker dev-status
source docker/dev_env.sh   # inside sando-dev
make -C docker dev-build
# replay example:
replay_integer_planning --input …/selected12.jsonl --output out.jsonl \
  --bc …/bc.json --cost …/cost.json --seed 101 --candidate-limit 1
```

## Next

1. Rebuild + stage7 matched arms with `--candidate-limit 1`.
2. Part1: fill observation fields or re-capture reconstructable snapshots; publish new model sha256.
3. Part2: re-run four arms + stage8 verify; optional selected60 formal campaign.
