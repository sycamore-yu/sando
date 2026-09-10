# SANDO paper closeout — live plan (plan2)

Authority: `docs/fromchat/plan2.md`  
Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
HEAD: see `git rev-parse HEAD`

## Rule

Do **not** declare All done until plan2 **§20 PAPER-LEVEL DEFINITION OF DONE** is fully evidenced.

## Progress

| Phase | Status | Evidence |
|---|---|---|
| 0–1 Env audit + formal set | **PASS** | `ENVIRONMENT_AUDIT.md`, `environment_manifest.json` |
| 2 Identity hashes | **PASS** | `IDENTITY_CHAIN.md` |
| 3 Geometry safety | **PASS** | `SAFETY_METRIC.md` |
| 4 QP parity | **PASS** | 50/50 `phase4_parity50.json` |
| 5 KKT freeze | **PASS** | 30/30 grad `GRADIENT_FREEZE.md` |
| 6 Train freeze | **PASS** | `FREEZE.json` (λ=1.0 DiffOpt) |
| 7–8 Formal A/B/C | **IN PROGRESS** | dry-run seed1000 PASS; launching matrices |
| 9–14 Stats / RQ / package | PENDING | |
| §20 Paper DoD | OPEN | |

## Next

Complete formal paired runs on independent groups; aggregate RQ1–RQ3; FINAL_DOD_AUDIT.
