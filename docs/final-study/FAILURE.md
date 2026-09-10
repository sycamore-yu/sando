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

## Phase L attribution (Case B) + mitigation probe
True Diff-QP λ=0.1 does not clearly beat supervised on task success (5/6 vs 6/6).

Seed200 T histogram (append successes):
- true_diff λ=0.1: **61.7%** of predicted T at F_MAX=2.5; mean T≈2.33
- supervised: **0%** at 2.5; mean T≈1.94

**Mitigation probe (λ_T=1.0 model, seeds 200–202):**
- F_MAX fraction drops to ~12–21%; mean T≈2.16–2.22
- Task success **3/3**; P50≈23.8 ms (≈ supervised)
- Evidence: `phase_l_case_b_lam1_mitigation.json` (203–205 extension in progress)

Next: finish 203–205; consider promoting λ=1.0 (or re-tune on train-only) as Case B resolution without deepening the net.
