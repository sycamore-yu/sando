# 00 Executive summary (paper package)

Filled from `FORMAL_AGGREGATE.json` / `PAIRED_BOOTSTRAP.json` / `FAILURE_ATTRIBUTION.json` (270 paired runs).

## Direct answers (plan2 Phase 14)

1. **Current method:** Observation → 1T (learned timing) → rebuild C(T) → 1Z (frozen corridor-cost) → 1 hard QP → append/publish. MIQP fallback allowed but counted separately from one-shot success.
2. **Change vs Original:** Replace online MIQP timing search with a frozen timing network (Supervised or DiffOpt λ=1.0); keep the same Z and hard QP.
3. **Who is faster?** **Learned one-shot is faster.** Across all three formal groups, Supervised and DiffOpt cut median P50 replan latency vs Original (paired bootstrap 95% CIs exclude 0). Largest gap on `unknown_dynamic_easy` (~−110 ms).
4. **Success / safety held?** **Goal-reached is comparable (~90–100%). Collision-free goal is low for all methods** and does **not** improve under learning (tie or slight Original edge on dynamic). Report goal and collision-free separately; do not claim a safety win.
5. **DiffOpt vs Supervised?** **No clear closed-loop DiffOpt win.** Latency mostly tied (easy/medium CIs include 0); on dynamic, DiffOpt is slightly *slower* than Supervised (+6.9 ms [3.4, 12.5]). Collision-free rates do not favor DiffOpt.
6. **DiffOpt research value?** Reproducible train→KKT→deploy chain with QP parity (50/50) and grad freeze evidence. On these formal tests, DiffOpt does **not** beat Supervised on online task/safety; value is methodological correctness, not a free performance lift.
7. **Scenes that support latency/oneshot conclusions:** all three independent groups (`procedural_static_{easy,medium}`, `unknown_dynamic_easy`).
8. **Unsupported / do not claim:** map generalization from legacy forest 200–229; safety improvement from learning; DiffOpt superiority over Supervised; “equivalent” from equal goal counts alone.
9. **Largest limitation:** Geometry-aware collision rates remain high (~70–100%) for all methods; dominant failure bucket is `execution_tracking`. Sample is 30×3 groups (not full hard/dynamic-medium matrix).

## Freeze

See `FREEZE.json`. Research baseline: `1e4f9f918113857026a9d3b406c6a6209b9b8ff8`. Z not restarted (`restart_Z_learning: false`).
