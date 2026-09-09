# Stage 6 geometry event review (§3.6)

Assumptions: you know stage2’s online `collision` flag means sampled AABB overlap (not proven physical contact), and forest trees are cylinders whose logged boxes are enclosing AABBs.

Machine copy: `docker/dev-workspace/results/request-latency-v2/stage6/analysis/geometry_review.md`.

## What the docs already say

From `docs/learning-stages-0-5.md`:

- Online `collision` = robot vs obstacle **axis-aligned box overlap at sample times** (“采样 AABB 重叠”).
- Forest cylinders use **enclosing AABBs** → conservative vs true cylinder geometry.
- Does **not** prove contact, and does **not** cover gaps between samples.
- Stage2 rates are high (e.g. original dynamic 14/18, forest easy often 18/18 AABB-positive in method tables / episode flags).

## Representative cases (traceable)

Prefer one dynamic + one forest; both `method=original`, `collision=true`, seed 200 from stage2-isolated (same episodes as `final-reports/stage2.json`).

| Case | Scene | Job path | AABB flag | First hit | Samples checked | Tracking error |
| --- | --- | --- | --- | --- | ---: | ---: |
| Dynamic | `unknown_dynamic-n100-d0.65-seed200` | `learning-stages-v2/stage2-isolated/jobs/unknown_dynamic-n100-d0.65-seed200-original/` | true | `obstacle_7` @ sim_t≈9.60, pos≈[4.03, −0.18, 1.82] | 1776 | 0.021 |
| Forest | `static_forest-easy-seed200` | `learning-stages-v2/stage2-isolated/jobs/static_forest-easy-seed200-original/` | true | model `21` @ sim_t≈92.83, pos≈[62.98, −1.10, 1.61] | 2704 | 0.011 |

Shared metric definition (both `run/result.json` → `ground_truth.collision.metric_definition`):

- name: `sampled_AABB_overlap`
- rule: per-axis `|robot_center − obstacle_center| ≤ (robot_bbox + obstacle_bbox)/2`
- robot bbox full size: `[0.2, 0.2, 0.2]` m
- `continuous_collision_proof: false`
- sample source: co-sampled `/plug/model_states_plug` after goal

## What can be recomputed from available logs

| Input | Dynamic case | Forest case |
| --- | --- | --- |
| AABB-positive summary + first_hit | yes (`result.json`) | yes |
| Robot bbox | yes (metric_definition) | yes |
| Obstacle box sizes | yes (`run/obstacles.json` scale_*) | yes (`run/forest_collision_geometry.json` size_*; also cylinder radius in `static_world.world`) |
| Robot odom path | yes (`ground_truth.odom_trace`, wall timestamps) | yes |
| Static obstacle XY centers / cylinder radii | n/a (moving boxes) | yes (world + geometry sizes; radius = size_x/2 for square enclosing AABB) |
| Dynamic obstacle analytic traj | yes (`obstacles.json` traj_*) | n/a |
| Min-clearance sample snippets | yes (partial list in collision block) | yes |

So we **can**:

1. Restate and spot-check the **recorded AABB decision** at `first_hit` using published centers/sizes **if** robot and obstacle poses at that sim time can be recovered.
2. For forest, compute the **nominal cylinder radius** from the world/geometry files and compare to the enclosing AABB half-extent (they match the usual `radius` ↔ `size_x/2` pattern).
3. Confirm the metric is sample-time only (`continuous_collision_proof: false`).

## What cannot be recomputed (blockers)

**Full cylinder-vs-robot recompute over the flight — blocked.**

Reasons:

1. **Co-sampled obstacle poses are not retained.** Logs keep the boolean, first_hit, and a short min-clearance list — not the full robot+obstacle pose series used for the 1776/2704 checks.
2. **Clock mismatch for naive odom join.** `odom_trace` uses wall `timestamp`; `first_hit_time` is sim time. Without a retained (sim_time ↔ wall_time) map or co-sampled obstacle frame, aligning odom to the first-hit sample is not exact.
3. **Forest:** `obstacles.json` is absent; geometry file stores AABB sizes (and world has cylinders) but not the per-sample model_states stream. Static centers can be parsed from the world, but without robot pose at the same sim stamp as `first_hit`, cylinder overlap at that event stays approximate.
4. **Dynamic:** obstacle motion is recoverable from `traj_*` **given sim t**, but the same sim↔wall alignment gap blocks joining to `odom_trace`. Box AABB recompute is the native metric; these obstacles are boxes, not cylinders.
5. **Inter-sample sweep / true contact** were never logged; cannot be invented from AABB flags.

## Distinction this review supports

| Question | Answer from these cases |
| --- | --- |
| Geometric conservatism (forest AABB vs cylinder)? | Documented in metric_definition + world cylinders; **not** re-evaluated sample-by-sample here. |
| Trajectory model violation? | Not addressed (no constraint residual tie-in at first_hit). |
| Tracking deviation? | Small tracking_error on both successes; does not explain AABB flag by itself. |
| Time misalignment? | Suspected risk when trying offline recompute (sim vs wall clocks). |

## Minimal follow-up to unblock cylinder review

Retain, for AABB-positive episodes: co-sampled `(sim_time, robot_pose, obstacle_poses[])` at least around first_hit (or full stream), plus obstacle shape type (`box`/`cylinder`) and radius. Then recompute AABB and cylinder at the same stamps and report both.

## References

- `docs/learning-stages-0-5.md` (AABB overlap notes)
- `learning-stages-v2/final-reports/stage2.json` episodes for the two scenes
- Job `run/result.json`, `run/obstacles.json` / `run/forest_collision_geometry.json`, `run/static_world.world`
