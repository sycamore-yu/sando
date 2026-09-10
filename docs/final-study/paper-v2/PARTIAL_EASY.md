# Partial formal result — procedural_static_easy only

**Not** paper DoD. Full matrix still running (`unknown_dynamic_easy`, `procedural_static_medium`).

Evidence:
- `FORMAL_AGGREGATE_partial_easy.json`
- `PAIRED_BOOTSTRAP_partial_easy.json`
- `FAILURE_ATTRIBUTION_partial_easy.json`

## Headline (n=30 paired)

| Method | Goal | Collision-free goal | Episodes with oneshot | P50 latency med (ms) |
|---|---:|---:|---:|---:|
| Original | 96.7% | 6.7% | 0% | 74.8 |
| Supervised | 96.7% | 6.7% | 100% | 58.0 |
| DiffOpt | 90.0% | 10.0% | 100% | 56.9 |

Paired bootstrap (easy only):

- Supervised−Original latency: **−16.4 ms** [−21.5, −10.7] — learned faster
- DiffOpt−Supervised latency: −4.0 ms [−10.1, +2.1] — **tie** (CI includes 0)
- Collision-free goal Δ Supervised−Original: 0 [−0.1, +0.1] — **tie**
- wrong_Z learned count: **0**; `restart_Z_learning: false`
- Dominant non-success bucket: `execution_tracking` (goal with geometry collision)

## Caution

Geometry-aware collision rate is high (~80–90%) for all methods on this group. Report goal and collision-free separately; do not claim safety win from goal-reached alone.
