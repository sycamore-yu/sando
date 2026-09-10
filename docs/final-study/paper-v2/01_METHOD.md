# 01 Method

Deploy path: **1T + 1Z + 1 hard QP** with MIQP fallback counted separately.

- **A Original:** production SANDO timing (no learned T oneshot).
- **B Supervised:** `timing-schema2-regression.json` + frozen `corridor-cost.json`.
- **C DiffOpt:** `timing_kkt_lam1.0_seed0.json` + same Z.

Training (DiffOpt): timing net → T → hard QP → trajectory loss → KKT/implicit grads → update T. Z frozen unless failure attribution proves wrong-Z dominates.

Details: `FREEZE.json`, `IDENTITY_CHAIN.md`, online via `integer_learning_baseline_sim.py`.
