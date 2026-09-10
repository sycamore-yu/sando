# IDENTITY

## Commit / branch
- Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`
- Engineering baseline: `103faa1`
- See `git log` / `docs/unified-plan.md` for study commits.

## Trajectory identity (live JSONL)
Planning row + follow-on events:
- `request_id`, `trajectory_id`, `predicted_T`, `fallback`, `actual_chosen_assignment`
- `kind=publish` → `publish_ms`
- `kind=controller_first_use` → `controller_first_use_ms`

Verified on Phase G seed200 and Phase K pilots (controller_first_use counts ≈ oneshot appends).

## Still open for full §3.5
- `planning_observation_hash` / corridor content hash on every event (capture path has sha256 helpers; not yet stamped on all replan events).
