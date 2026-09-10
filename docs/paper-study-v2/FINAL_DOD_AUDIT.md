# Paper-level DoD audit (plan2 §20) — living checklist

Authority: `docs/fromchat/plan2.md` §20  
Update only with evidence paths. Do not mark All done until every box is PASS.

## METHOD

| Item | Status | Evidence |
|---|---|---|
| True Diff-QP train chain reproducible | PASS | `prototypes/time_fixed_z_qp/train_true_diff_timing.py`, `FREEZE.json` λ=1.0 |
| KKT gradient correctness | PASS | `GRADIENT_FREEZE.md`, `phase5_grad_validation_pack30.json` |
| Python QP ≡ production Bezier fixed-Z | PASS | `QP_EQUIVALENCE_AUDIT.md`, `phase4_parity50.json` (50/50) |
| Online 1T+1Z+1QP | PASS | one-shot path + dry-run oneshot counts |

## ENVIRONMENT

| Item | Status | Evidence |
|---|---|---|
| Repeated vs independent maps distinguished | PASS | `ENVIRONMENT_AUDIT.md` |
| Formal test uses new independent envs | IN PROGRESS | `paper_procedural_static_*`, `paper_unknown_dynamic_*` |
| Static + dynamic independent realizations | IN PROGRESS | groups in `environment_manifest.json` |
| Manifest + hash per env | PASS | `environment_manifest.json` |

## FAIRNESS

| Item | Status | Evidence |
|---|---|---|
| A/B/C same environments | IN PROGRESS | paired seeds in formal runner |
| Supervised/DiffOpt same online arch | PASS | `FREEZE.json` / `run_paper_formal.sh` |
| Models frozen pre-test | PASS | `FREEZE.json` |
| No test tuning | PASS | freeze note + seed lock |

## ONLINE

| Item | Status | Evidence |
|---|---|---|
| Closed-loop Gazebo | PASS | `integer_learning_baseline_sim.py` |
| Sensing/map + replan + append/publish | PASS | metrics + dry-run |
| Controller first-use | PASS | dry-run `controller_first_use_events` |
| UAV execution | PASS | goal/collision from model states |

## SAFETY

| Item | Status | Evidence |
|---|---|---|
| Not AABB forest proxy as claim | PASS | `SAFETY_METRIC.md` |
| Geometry-aware + clearance | PASS | baseline sim fields |
| collision-free task success | IN PROGRESS | formal aggregate |
| Feasibility vs execution separated | PASS | `STATISTICS.md` definitions |

## RESULTS / SCIENCE / REPRO

| Item | Status | Evidence |
|---|---|---|
| ≥3 methods, ≥3 independent groups, pre-reg N | IN PROGRESS | formal matrix running |
| latency / oneshot / task / safety / attribution / CI | PENDING | after matrix |
| RQ1–RQ3 qualitative answers | PENDING | |
| Repro package (SHA, models, commands, raw paths) | PENDING | `docs/paper-study-v2/` package |

## Gate

All done only when every row is PASS with concrete evidence.
