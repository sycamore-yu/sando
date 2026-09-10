# Statistics protocol (plan2 Phase 10) — frozen before formal results

Authority: `docs/fromchat/plan2.md` §15  
Frozen with: `docs/paper-study-v2/FREEZE.json`  
This file must not be rewritten after looking at formal outcomes.

## Primary episode outcomes

| Name | Definition |
|---|---|
| `goal_reached` | Simulator reports goal reached |
| `collision` | Geometry-aware sampled clearance ≤ 0 (not AABB proxy) |
| `collision_free_goal_reached` | `goal_reached` AND `collision == false` |
| `oneshot_success` | Append succeeded with no MIQP/T/Z fallback on that request |
| Planning feasibility | Hard-QP residual validity / append success (separate from execution safety) |

Report rates with **Wilson or Clopper–Pearson 95% CI** (binomial).  
For paired A/B/C on the same `environment_id`: **McNemar** or paired bootstrap on success indicators.  
Do **not** claim “equivalent” from equal counts alone.

## Latency

- Per episode: replan latency P50 / P95 from metrics  
- Across episodes: median of per-episode P50  
- Paired Δ: Learned−Original, DiffOpt−Supervised with bootstrap 95% CI on paired differences

## Continuous metrics

When available: episode time, min clearance, tracking error.  
Report median and paired Δ with bootstrap 95% CI.

## Failure attribution (required categories)

For each failed or collision episode, assign one primary bucket:

1. `timing_T` — predicted T drives infeas / saturation  
2. `wrong_Z` — corridor assignment primary cause  
3. `map_sensing` — incomplete / stale map  
4. `optimizer` — QP / residual failure with plausible T/Z  
5. `execution_tracking` — plan feasible but tracking/collision in execution  
6. `other` / `unknown`

Wrong-Z only restarts Z learning if it dominates failures on formal independent tests.

## Formal sample (pre-registered)

See `environment_manifest.json` / `FREEZE.json`:

- procedural_static_easy: 30  
- procedural_static_medium: 30  
- unknown_dynamic_easy: 30  
- Methods: Original, Supervised, DiffOpt (paired)

Legacy forest 200–229 is **not** a map-generalization sample.
