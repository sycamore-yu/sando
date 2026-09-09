# Request-latency execution plan (Part2 unique progress entry)

Updated: 2026-09-09 (batch after `3a13bf9` continuation doc)

## Identity

- Doc base: `3a13bf9`
- Results: `docker/dev-workspace/results/request-latency-v3/` (new round)
- Prior: `request-latency-v2/` retained read-only

## Final main-chain budget

One T · one full z · ≤1 main hard QP · residual+freshness · append/publish.  
Fallback = separate safety metrics. One-shot success ≠ system final success.

## Batch 1 progress (existing data / code)

| Item | Status | Evidence |
|------|--------|----------|
| Split selected60 first vs fallback | **done** | `v3/analysis/selected60_first_vs_fallback.*` |
| Fix verify+compile skip | **done** | `ampls_runtime.cpp` + `ampl_persistent_updates` |
| Fix previous candidate overflow | **done** | replay + gurobi + probes |
| Recreate keeps candidate limit | **done** | `sando.cpp` + online_corridor probe |
| Fresh vs persistent reuse | **done** | `v3/analysis/fresh_vs_persistent.*` (~3.9× wall) |
| Forest cylinder proxy | **done** | `v3/geometry/forest_cylinder_proxy.*` |
| Part1 §5 interface checklist | **done** | `docs/request-latency-v2/PART1_INTERFACE_CHECKLIST.md` |
| Online 4-scene timing | **running/queued** | `v3/config/online_timing_dev4.json` |

## Batch 2 (blocked on Part1)

| Delivery | Unlocks |
|----------|---------|
| I1 complete observation | multi-T rebuild |
| I2 real new-time queryer | stage7 time_only/joint offline |
| I3 T1/T2/T3 models | corresponding stage7 arms + stage8 verify |

## Commands

```bash
make -C docker dev-status
make -C docker dev-build
make -C docker dev-test
# inside sando-dev + source docker/dev_env.sh
replay_integer_planning ... --candidate-limit 1 --runtime-reuse fresh|persistent
```
