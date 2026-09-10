# Environment independence audit (plan2 Phase 0)

Authority: `docs/fromchat/plan2.md`  
Baseline commit: `1e4f9f918113857026a9d3b406c6a6209b9b8ff8`  
Companion: `docs/paper-study-v2/environment_manifest.json`

## Verdict

| Scene setup | Seeds change geometry? | Role for paper |
|---|---|---|
| Phase K/M default `static_forest` n=50 seeds 200–229 | **No** — one fixed `easy_forest.world` | Same-map runtime stability only |
| `unknown_dynamic` + `dynamic_ratio=0` | **Yes** — independent static box layouts | Formal **procedural_static** generalization |
| `unknown_dynamic` + `dynamic_ratio=0.65` | **Yes** — layout + trefoil trajectories | Formal **unknown_dynamic** generalization |

Historical forest 29/30 results remain valid as **repeatability on one map**, not as 30 independent environments.

## Answers required by plan2 §5

1. **static_forest easy/medium/hard are fixed worlds.**  
   Difficulty only selects `worlds/{easy,medium,hard}_forest.world`. Launch sets `same_map_across_seeds: True` and `num_obstacles: 0` (trees live in the SDF).

2. **Seed does not change static forest geometry.**  
   Seed is an episode / output-dir label. Pilots use `--start-randomization none`, so start/goal stay nominal `(0,0,2)` → `(105,0,2)`.

3. **unknown_dynamic seed does change obstacle realization.**  
   `_generate_obstacle_json(..., seed, ..., dynamic_ratio=...)` reseeds Python `random` and rebuilds the obstacle list.

4. **Dynamic trajectory seed does change motion** when `dynamic_ratio=0.65`.  
   First `int(n * 0.65)` obstacles get time-varying trefoil `traj_*` expressions. With `dynamic_ratio=0`, all obstacles are static boxes (positions still seed-dependent).

## Evidence map

| Claim | Location |
|---|---|
| Forest `same_map_across_seeds` | `scripts/integer_scene_protocol.py` `launch_spec` |
| Forest copies packaged world | `scripts/integer_learning_baseline_sim.py` (copy `*.world`) |
| Seeded procedural obstacles | `scripts/run_sim.py` `_generate_obstacle_json` |
| Phase M defaults forest + seeds 200–229 | `scripts/run_phase_m_expand.sh` |
| Layout fingerprint helper | `scripts/run_integer_learning_evaluation.py` `layout_sha` |

## Measured hashes (this audit)

- `easy_forest.world` SHA-256: `3734f825cb1b9a48dc320e9b377aa63449ed3ae52b7a699615d855deab154e22`
- `unknown_dynamic` n=50 d=0 seeds 200–209: **10 unique** obstacle content hashes
- `unknown_dynamic` n=50 d=0.65 seeds 200–202: **3 unique** hashes

## Pre-registered formal environment groups

See `environment_manifest.json` (180 environments). Pre-registration is frozen before formal A/B/C runs; seeds are not cherry-picked by outcome.

| Group | Family | n | d | Seeds | Independent |
|---|---|---|---|---|---|
| `legacy_static_forest_easy_repeat` | static_forest | 50→easy world | 0 | 200–229 | No (1 map) |
| `procedural_static_easy` | unknown_dynamic | 50 | 0 | 1000–1029 | Yes |
| `procedural_static_medium` | unknown_dynamic | 100 | 0 | 1100–1129 | Yes |
| `procedural_static_hard` | unknown_dynamic | 200 | 0 | 1200–1229 | Yes |
| `unknown_dynamic_easy` | unknown_dynamic | 50 | 0.65 | 2000–2029 | Yes |
| `unknown_dynamic_medium` | unknown_dynamic | 100 | 0.65 | 2100–2129 | Yes |

## Recommendation (locked for Phase 1+)

- Keep legacy forest as **fixed-map / latency stability** benchmark.
- Use `unknown_dynamic` + `dynamic_ratio=0` as **procedural_static** for map generalization (plan2 §6.1).
- Pair Original / Supervised / DiffOpt on identical `environment_id` + manifest hashes.
