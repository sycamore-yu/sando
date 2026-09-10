# IDENTITY

## Commit / branch
- Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`
- Engineering baseline: `103faa1`
- Freeze: `docs/final-study/FREEZE.json` (λ_T=1.0 primary timing)

## Trajectory identity (live JSONL)
Planning row + follow-on events:
- `request_id`, `trajectory_id`, `predicted_T`, `fallback`
- `z_id`, `corridor_method`
- `planning_observation_hash` (sha256 of canonical planning JSON)
- `corridor_hash` (sha256 of T/Z/corridor identity JSON)
- `kind=publish` → `publish_ms`
- `kind=controller_first_use` → `controller_first_use_ms`

Smoke evidence: `docs/request-latency-v2/evidence/analysis/phase_j_identity_hash_smoke.json`  
(seed200: 1093 appends with hashes + controller_first_use).

## Distinguishes
- main one-shot: `fallback=false` + append + publish + controller_first_use
- fallback success: `fallback=true` + append …
- planning failure: `append_success=false` / `failure_stage`
- execution failure: episode `goal_reached=false` / timeout
