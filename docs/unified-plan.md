# SANDO paper closeout — live plan (plan2)

Authority: `docs/fromchat/plan2.md`  
Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
Research baseline (do not redo): `1e4f9f918113857026a9d3b406c6a6209b9b8ff8`  
Prior §3 study package: `docs/final-study/` (frozen historical evidence)

## Rule

Do **not** declare All done until plan2 **§20 PAPER-LEVEL DEFINITION OF DONE** is fully evidenced.
Milestone PASS = evidence + analyze + commit + push + continue.

## Progress

| Phase | Status | Evidence |
|---|---|---|
| 0 Environment audit | **PASS** | `docs/paper-study-v2/ENVIRONMENT_AUDIT.md`, `environment_manifest.json` |
| 1 Formal independent env set | **PASS** (pre-registered) | 180 envs in `environment_manifest.json` |
| 2 Paper identity chain | IN PROGRESS | Current obs/corridor hashes are summary-only; need content hashes |
| 3 Geometry-aware safety | PENDING | Replace AABB forest proxy |
| 4 QP equivalence audit | PENDING | `QP_EQUIVALENCE_AUDIT.md` |
| 5 KKT gradient freeze | PENDING | Expand validation pack |
| 6 Train protocol freeze | PENDING | |
| 7 Method groups A/B/C | PENDING | Original / Supervised / DiffOpt |
| 8 Formal closed-loop | PENDING | Paired on formal envs |
| 9–11 Metrics / stats / RQ | PENDING | |
| 12 Z restart gate | PENDING | Only if wrong-Z dominates |
| 13–14 Figures + package | PENDING | `docs/paper-study-v2/` |
| §20 Paper DoD | OPEN | |

## Next actions

1. Upgrade online `planning_observation_hash` / `corridor_hash` to real content hashes (map voxels / corridor A,b).
2. Geometry-aware collision + clearance metric.
3. QP equivalence + KKT expand.
4. Freeze models; dry-run one env × A/B/C; launch formal matrix.
