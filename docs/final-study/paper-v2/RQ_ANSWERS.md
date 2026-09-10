# RQ1–RQ3 answers (formal evidence)

Sources: `FORMAL_AGGREGATE.json`, `PAIRED_BOOTSTRAP.json`, `FAILURE_ATTRIBUTION.json`, `final/TABLE_*.md`.  
Stats protocol: `STATISTICS.md` (Wilson + paired bootstrap). Do not claim equivalence from equal counts alone.

## Per-group snapshot (n=30 each)

| Group | Method | Goal | CF-goal | Oneshot eps | P50 med (ms) |
|---|---|---:|---:|---:|---:|
| static easy | Original | 96.7% | 6.7% | 0% | 74.8 |
| static easy | Supervised | 96.7% | 6.7% | 100% | 58.0 |
| static easy | DiffOpt | 90.0% | 10.0% | 100% | 56.9 |
| dynamic easy | Original | 100% | 30.0% | 0% | 197.3 |
| dynamic easy | Supervised | 96.7% | 20.0% | 100% | 82.7 |
| dynamic easy | DiffOpt | 100% | 16.7% | 100% | 87.5 |
| static medium | Original | 96.7% | 0% | 0% | 80.5 |
| static medium | Supervised | 100% | 0% | 100% | 61.5 |
| static medium | DiffOpt | 90.0% | 0% | 100% | 61.2 |

## RQ1 — Learned one-shot vs Original

**Latency / oneshot:** Learned wins. Supervised−Original P50 mean Δ (ms) with 95% CI:

- static easy: −16.4 [−21.5, −10.7]
- dynamic easy: −115.7 [−121.7, −111.5]
- static medium: −17.0 [−19.8, −11.9]

Every learned episode used oneshot appends (100%); Original oneshot rate is structurally ~0 (MIQP path) — compare latency/task/safety, not oneshot counts as a fair contest against Original.

**Task / safety:** Goal-reached stays high and similar. Collision-free goal does **not** improve under learning (CIs for Δ include 0 or favor Original slightly on dynamic). Cost of speed: no evidence of a safety gain; medium density is collision-dominated for all methods (0% CF-goal).

## RQ2 — DiffOpt vs Supervised

**Latency:** DiffOpt−Supervised:

- static easy: −4.0 [−10.1, +2.1] (tie)
- dynamic easy: **+6.9 [+3.4, +12.5]** (DiffOpt slower)
- static medium: −4.5 [−10.5, +0.5] (tie)

**Collision-free:** no DiffOpt advantage (Δ CIs include 0 or are ~0).

**Qualitative:** Closed-loop DiffOpt does not beat Supervised here. Keep DiffOpt claims at method correctness (QP parity + KKT grads), not online superiority.

## RQ3 — Why (failure attribution)

- `wrong_Z_count_learned`: **0**
- `restart_Z_learning`: **false** → **Z stays frozen**
- Dominant non-success: `execution_tracking` (goal reached with geometry-aware collision)
- Not primarily wrong-T / wrong-Z / optimizer on this attribution scheme

## Limitations

- High geometry collision rates across methods; metric is stricter than AABB and often negative median clearance.
- Formal N=30×3; no hard / dynamic-medium full matrix in this package.
- Original oneshot metric asymmetry.
