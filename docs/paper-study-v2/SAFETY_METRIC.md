# Geometry-aware safety metric (plan2 Phase 3)

Authority: `docs/fromchat/plan2.md` §8

## Change

Online episode collision evaluation no longer uses forest cylinder enclosing-AABB as the paper claim.

Primary metric (`scripts/integer_learning_baseline_sim.py`):

- Robot: enclosing sphere of the drone AABB
- Obstacle: cylinder (radius, height) or box (size_x/y/z)
- Collision if exterior clearance ≤ 0
- Episode fields: `collision`, `minimum_clearance`, `time_of_min_clearance`, `obstacle_id`, `vehicle_position`

Legacy AABB proxy is retained as `aabb_proxy_collision` for false-positive comparison only.

## Separation

Planning feasibility (hard-QP residuals / one-shot success) and execution safety (geometry-aware collision-free) are reported separately.
