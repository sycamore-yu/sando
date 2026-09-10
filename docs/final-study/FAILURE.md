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
True Diff-QP does not clearly beat supervised on task success. Next checks (no deeper net): T saturation, feature sufficiency, feasibility distribution, train/test mismatch — not Z (fallback≈0).
