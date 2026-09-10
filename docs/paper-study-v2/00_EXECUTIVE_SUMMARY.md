# 00 Executive summary (paper package)

Status: draft until `FORMAL_COMPLETE.json` exists. Numbers below must be filled from `final/TABLE_MAIN.md`.

## Direct answers (plan2 Phase 14)

1. **Current method:** Observation → 1T (learned timing) → rebuild C(T) → 1Z (frozen corridor-cost) → 1 hard QP → append/publish. MIQP fallback allowed but counted separately.
2. **Change vs Original:** Replace online MIQP timing search with a frozen timing network (Supervised or DiffOpt); keep same Z + hard QP.
3. **Who is faster?** PENDING formal P50/P95.
4. **Success / safety held?** PENDING collision-free goal rates (geometry-aware, not AABB).
5. **DiffOpt vs Supervised?** PENDING paired bootstrap.
6. **DiffOpt research value?** PENDING — report even if tie/negative without hype.
7. **Scenes that support?** Formal independent groups only (`procedural_static_{easy,medium}`, `unknown_dynamic_easy`).
8. **Unsupported?** Legacy forest 200–229 repeated map — not map generalization.
9. **Largest limitation?** PENDING after attribution (likely sample size / collision rate / oneshot vs Original metric asymmetry).

## Freeze

See `FREEZE.json`. Baseline research commit: `1e4f9f918113857026a9d3b406c6a6209b9b8ff8`.
