# Static forest cylinder proxy vs enclosing AABB (§4.4)

Assumptions: you know stage2 `collision` is sample-time AABB overlap, forest trees are Gazebo cylinders logged as enclosing boxes, and this check is discrete per pose (not continuous-time).

Machine copies: `docker/dev-workspace/results/request-latency-v3/geometry/forest_cylinder_proxy.{json,md}`.

## Verdict

World trees are **vertical cylinders** (roll=pitch=0, length along +Z). On odom poses from three AABB-positive stage2 forest flights, the cylinder–robot AABB proxy is **strictly tighter** than the enclosing-box AABB: **cylinder-only = 0** everywhere; **AABB-only > 0**. Recorded online `first_hit_position` is AABB-positive but **cylinder-negative** on all three flights — the first logged AABB event can be a corner-of-box false alarm vs the true cylinder.

This is a **per-sample discrete** recompute on `odom_trace`. It is **not** continuous-time collision. Exact first-AABB-event **time** alignment to odom remains **blocked** (sim vs wall clocks; no co-sampled pose stream).

## Robot proxy

| Source | Value |
| --- | --- |
| Online metric `robot_bbox_full_size_m` | `[0.2, 0.2, 0.2]` m |
| Half-sizes used here | `hx=hy=hz=0.1` m |
| `config/sando.yaml` `drone_bbox` | `[0.2, 0.2, 0.2]` |
| Planner `drone_radius` | `drone_bbox[0]/2` = `0.1` m |

## Formula (axes verified)

Tree center `c`, radius `r`, height `H`. Robot center `p`, half-sizes `hx,hy,hz`.

```
dx = max(|px-cx| - hx, 0)
dy = max(|py-cy| - hy, 0)
planar:  dx² + dy² ≤ r²
height:  |pz-cz| ≤ hz + H/2
both => cylinder proxy intersect at that sample
```

Enclosing AABB (online metric shape): `|px-cx|≤hx+r` and `|py-cy|≤hy+r` and `|pz-cz|≤hz+H/2`.

World: cylinder default axis +Z; model pose `cz=3`, `H=6` → trunks from z=0..6. No collision-local pose offset.

## World-shape verification (easy / medium / hard)

| Env | # cylinders | vertical | H / cz | r range (m) | geo AABB = 2r×2r×H | SHA match `worlds/*_forest.world` |
| --- | ---: | --- | --- | --- | --- | --- |
| easy | 41 | yes | 6.0 / 3.0 | 1.01082–1.49139 | yes | yes |
| medium | 81 | yes | 6.0 / 3.0 | 1.01082–1.49971 | yes | yes |
| hard | 162 | yes | 6.0 / 3.0 | 1.00000–1.49971 | yes | yes |

Parsed from each job’s `run/static_world.world` + `run/forest_collision_geometry.json`.

## Flights (odom per-sample)

Pose source: `ground_truth.odom_trace` (wall unix `timestamp` + `position`). Online AABB used a different stream (`/plug/model_states_plug` after goal); counts below compare **AABB vs cylinder on the same odom samples**.

| Job | Online AABB flag | Online samples | Odom samples | AABB+ | cyl+ | both | AABB-only | cyl-only |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `static_forest-easy-seed200-original` | True | 2704 | 4417 | 285 | 251 | 251 | 34 | 0 |
| `static_forest-hard-seed200-original` | True | 1334 | 3409 | 527 | 449 | 449 | 78 | 0 |
| `static_forest-medium-seed200-original` | True | 2213 | 4173 | 163 | 152 | 152 | 11 | 0 |

### First-hit position spot-check (recorded online pose)

At `first_hit_position` from `result.json` (no time join needed):

- `static_forest-easy-seed200-original`: recorded `['21']` @ sim_t≈92.833; recomputed AABB hits `['21']`, cylinder hits `[]` (AABB-only at first logged event).
- `static_forest-hard-seed200-original`: recorded `['154']` @ sim_t≈86.808; recomputed AABB hits `['154']`, cylinder hits `[]` (AABB-only at first logged event).
- `static_forest-medium-seed200-original`: recorded `['21']` @ sim_t≈91.902; recomputed AABB hits `['21']`, cylinder hits `[]` (AABB-only at first logged event).

## Synthetic formula self-check (tree `21` easy)

| Case | AABB | cylinder |
| --- | --- | --- |
| tree_center | True | True |
| inside_cylinder_offset_x_0.5 | True | True |
| aabb_corner_boundary_expected_aabb_only | True | False |
| outside_both | False | False |
| above_height_gap | False | False |

Corner case `aabb_corner_boundary_expected_aabb_only` confirms AABB can fire without cylinder.

## Blockers still open

| Need | Status | Paths searched / note |
| --- | --- | --- |
| Co-sampled robot+obstacle poses | missing | `min_clearance_samples` has only `sim_time`, `receipt_time`, `min_clearance_m` |
| Rosbags | not found | `stage2-isolated/jobs/static_forest*/**/*.bag` |
| Standalone odom CSV | not found | odom only inside `result.json` |
| Sim↔wall time map | missing | blocks aligning `first_hit_time` to an odom index by clock |

## Disclosure

- Discrete samples only; gaps between samples unproven.
- Not a continuous-time sweep.
- First AABB **event time** alignment remains blocked; position-level cylinder vs AABB comparison is available and was done.
