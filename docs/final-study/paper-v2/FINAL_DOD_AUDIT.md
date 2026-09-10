# Paper-level DoD audit (plan2 §20) — FINAL

Authority: `docs/fromchat/plan2.md` §20  
Commit at formal complete: see `FORMAL_COMPLETE.json`.  
Every box below is PASS only with listed evidence.

## METHOD

| Item | Status | Evidence |
|---|---|---|
| True Diff-QP train chain reproducible | PASS | `train_true_diff_timing.py`, `FREEZE.json` λ=1.0 model |
| KKT gradient correctness | PASS | `GRADIENT_FREEZE.md`, `phase5_grad_validation_pack30.json` |
| Python QP ≡ production Bezier fixed-Z | PASS | `QP_EQUIVALENCE_AUDIT.md`, `phase4_parity50.json` 50/50 |
| Online 1T+1Z+1QP | PASS | formal learned runs: oneshot 100% episodes; MIQP fallback counted separately |

## ENVIRONMENT

| Item | Status | Evidence |
|---|---|---|
| Repeated vs independent maps distinguished | PASS | `ENVIRONMENT_AUDIT.md` |
| Formal test uses new independent envs | PASS | seeds 1000–1029 / 1100–1129 / 2000–2029 |
| Static + dynamic independent realizations | PASS | procedural static + unknown_dynamic d=0.65 |
| Manifest + hash per env | PASS | `environment_manifest.json` |

## FAIRNESS

| Item | Status | Evidence |
|---|---|---|
| A/B/C same environments | PASS | 270 paired rows in `FORMAL_AGGREGATE.json` |
| Supervised/DiffOpt same online arch | PASS | `FREEZE.json` / `run_paper_formal.sh` |
| Models frozen pre-test | PASS | `FREEZE.json`, `REPRO_HASHES.json` |
| No test tuning | PASS | freeze note; formal after freeze |

## ONLINE

| Item | Status | Evidence |
|---|---|---|
| Closed-loop Gazebo | PASS | `integer_learning_baseline_sim.py` formal matrices |
| Sensing/map + replan + append/publish | PASS | metrics + oneshot/fallback counts |
| Controller first-use | PASS | `controller_first_use_events` in summaries |
| UAV execution | PASS | goal/collision from model states |

## SAFETY

| Item | Status | Evidence |
|---|---|---|
| Not AABB as paper claim | PASS | `SAFETY_METRIC.md` |
| Geometry-aware + clearance | PASS | result `ground_truth.collision` fields |
| collision-free task success reported | PASS | `final/TABLE_SAFETY.md` |
| Feasibility vs execution separated | PASS | `STATISTICS.md` + attribution |

## RESULTS

| Item | Status | Evidence |
|---|---|---|
| ≥3 methods | PASS | Original / Supervised / DiffOpt |
| ≥3 independent scene groups | PASS | easy static, medium static, easy dynamic |
| Pre-registered N completed | PASS | 30×3×3 = 270; `FORMAL_COMPLETE.json` |
| latency / oneshot / task / safety / attribution / CI | PASS | tables + bootstrap + Wilson |

## SCIENTIFIC ANSWER

| Item | Status | Evidence |
|---|---|---|
| Learned vs Original advantage/cost | PASS | `RQ_ANSWERS.md` RQ1 — latency win; safety not improved |
| DiffOpt vs Supervised qualitative | PASS | `RQ_ANSWERS.md` RQ2 — no clear DiffOpt online win |
| No hype on negative/tie | PASS | executive summary + limitations |
| Limitations explicit | PASS | `09_LIMITATIONS.md` |

## REPRODUCIBILITY

| Item | Status | Evidence |
|---|---|---|
| commit SHA / model SHA / manifests / commands / raw paths | PASS | `REPRO.md`, `REPRO_HASHES.json`, `FORMAL_COMPLETE.json` |
| frozen final package | PASS | `docs/paper-study-v2/` + sync `docs/final-study/paper-v2/` |

## Gate

**All §20 boxes PASS with evidence.** Paper-level closeout complete.
