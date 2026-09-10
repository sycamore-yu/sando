# Formal dry-run (plan2 Phase 8 gate)

Environment: `procedural_static_easy` seed **1000** (independent map, `unknown_dynamic` d=0 n=50)  
OUT: `docker/dev-workspace/results/request-latency-v3/online/paper_dryrun_seed1000_v2/`  
Commit at run: `2786a76` (seed-split unlock)

## Pairing check

| Method | goal_reached | oneshot_no_fallback | latency P50 ms | geometry collision | min_clearance m |
|---|---|---|---|---|---|
| A Original | yes | 0 (MIQP search) | 75.6 | yes | -0.020 |
| B Supervised | yes | 426 | 58.6 | no | +0.057 |
| C DiffOpt λ=1.0 | yes | 456 | 58.2 | yes | -0.124 |

Controller first-use events present for all three. Identity hashes active in binary.

## Gate

PASS for launching formal paired matrix (seed lock fixed; A/B/C share seed 1000).

Caveat: episode `success` currently follows goal-reached; paper tables must report **collision_free_goal_reached** from geometry-aware metric separately.
