# IDENTITY

## Commit / branch
- Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`
- Engineering baseline: `103faa1`
- See `git log` / `docs/unified-plan.md` for study commits.

## Trajectory identity (live JSONL)
Planning row + follow-on events:
- `request_id`, `trajectory_id`, `predicted_T`, `fallback`, `actual_chosen_assignment`
- `z_id` (comma-joined assignment), `corridor_method` (`learned`/`previous`/`original`)
- `kind=publish` → `publish_ms`
- `kind=controller_first_use` → `controller_first_use_ms`

Verified on Phase G seed200 and Phase K pilots (controller_first_use counts ≈ oneshot appends).

## Still open for full §3.5
- Full `planning_observation_hash` / map corridor content hash (capture path has sha256 helpers; not yet stamped on every online replan).
