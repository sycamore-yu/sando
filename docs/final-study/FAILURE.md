# FAILURE

## Offline
- Diff-QP / FD timing: 14/16 main QP accept vs supervised 15/16 (failures retained).
- Pack item with failed solution-probe in Phase D kept.

## Online (pilots 200–205)
- **true_diff seed201**: observation timeout; only ~20 oneshot appends; **kept in denominator**.
- Recurring stages (not deleted): `corridor_decomposition`, `optimization`.
- Online predicted_T often **saturates at 2.5 (F_MAX)** — train/online feature mismatch candidate.

## Install footgun
ROS loads `install-dev/sando/lib/sando/sando`. Flat `cmake --install` into `install-dev/lib/sando` must be copied into the package path or instrumentation/oneshot flags silently run on a stale binary.

## Phase L attribution (Case B)
True Diff-QP does not clearly beat supervised on task success (5/6 vs 6/6).

Seed200 T histogram (append successes):
- true_diff: **61.7%** of predicted T at F_MAX=2.5; mean T≈2.33
- supervised: **0%** at 2.5; mean T≈1.94

Evidence: `docs/request-latency-v2/evidence/analysis/phase_l_case_b_T_saturation.json`.

Next checks (no deeper net): feature sufficiency / train–online mismatch / feasibility under saturated T — not Z (`fallback≈0`).
