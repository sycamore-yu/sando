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
| 7–8 Formal A/B/C | **PASS** | 270/270; `FORMAL_COMPLETE.json` |
| 9 Stats / CI | **PASS** | `STATISTICS.md`, Wilson + `PAIRED_BOOTSTRAP.json` |
| 10–14 RQ / package | **PASS** | `RQ_ANSWERS.md`, `00_EXECUTIVE_SUMMARY.md`, `final/` |
| §20 Paper DoD | **PASS** | `FINAL_DOD_AUDIT.md` / `.json` |

## Headline (do not overclaim)

Learned oneshot **faster** than Original; **no** collision-free safety win; DiffOpt **≠** Supervised online win; **Z stays frozen**.
