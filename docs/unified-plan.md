# SANDO paper closeout — live plan (plan2)

Authority: `docs/fromchat/plan2.md`  
Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
Research baseline: `1e4f9f918113857026a9d3b406c6a6209b9b8ff8`  
HEAD progress beyond baseline includes Phase 0–5 paper closeout work.

## Rule

Do **not** declare All done until plan2 **§20 PAPER-LEVEL DEFINITION OF DONE** is fully evidenced.

## Progress

| Phase | Status | Evidence |
|---|---|---|
| 0 Environment audit | **PASS** | `ENVIRONMENT_AUDIT.md`, `environment_manifest.json` |
| 1 Formal independent env set | **PASS** | 180 pre-registered envs |
| 2 Identity content hashes | **PASS** | `IDENTITY_CHAIN.md` + rebuilt binary |
| 3 Geometry-aware safety | **PASS** | `SAFETY_METRIC.md` |
| 4 QP equivalence | **PASS** | `QP_EQUIVALENCE_AUDIT.md`; **50/50** forward parity |
| 5 KKT gradient freeze | **PASS** | `GRADIENT_FREEZE.md`; 30/30 grad, 29/30 full |
| 6 Train protocol freeze | IN PROGRESS | Reuse λ=1.0 DiffOpt + supervised init |
| 7–8 Formal A/B/C closed-loop | PENDING | Paired on formal envs |
| 9–14 Stats / RQ / package | PENDING | |
| §20 Paper DoD | OPEN | |

## Next

1. Freeze paper train/val/test manifests + model SHA (`FREEZE.json` under paper-study-v2).
2. Dry-run one formal env × Original / Supervised / DiffOpt.
3. Launch paired formal matrix on procedural_static + unknown_dynamic groups.
