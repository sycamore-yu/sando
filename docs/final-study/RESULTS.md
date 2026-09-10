# RESULTS

## Offline pack16 (fixed Z from pack assignment)

| Method | Accept | Rate | Mean jerk (accepted) | Mean T |
|---|---:|---:|---:|---:|
| capture_factor oracle | 16/16 | 1.000 | 88365 | 1.42 |
| supervised_init | 15/16 | 0.938 | 51431 | 1.51 |
| true-diff KKT λ=0 (Phase F) | 14/16 | 0.875 | ~19038 | ~1.89 |
| true-diff KKT λ=0.1 (Phase F) | 14/16 | 0.875 | ~19149 | ~1.77 |
| FD-proxy λ=0 | 14/16 | 0.875 | ~19042 | ~1.87 |

Evidence: `prototypes/time_fixed_z_qp/evidence/phase_{e,f}_train/offline_oneshot_compare.json`.

## Online pilots seeds 200–205 (static_forest, 50 obs)

Frozen Z: `corridor-cost.json` for one-shot methods. Instrumentation: publish + controller_first_use.

| Method | Task success | Goal reached | Mean P50 ms | Mean P95 ms | Notes |
|---|---:|---:|---:|---:|---|
| A Original SANDO | 6/6 | 6/6 | 38.6 | ~52 | multi-factor; not one-shot |
| B Supervised one-shot | 6/6 | 6/6 | 24.0 | 33.0 | |
| C FD-proxy one-shot | _pending_ | | | | `phase_k_fd` running |
| D True Diff-QP λ=0.1 | 5/6 | 5/6 | 21.7 | 29.7 | seed201 timeout retained |

Evidence: `docs/request-latency-v2/evidence/analysis/phase_k_pilots_compare.json`.

### Latency takeaway
One-shot methods cut planning P50 vs Original (~22–24 vs ~39 ms). True-diff is slightly faster than supervised but loses one task success.

### Phase G seed200 probe
goal_reached; 956 oneshot appends; 956 controller_first_use; fallback=0.

## Phase L decision
**Case B**: true-diff not clearly better than supervised on task success. Do **not** expand to 200–229 yet.

Attribution: online true-diff T saturates at F_MAX=2.5 (61.7% of appends on seed200) vs supervised 0% — see `phase_l_case_b_T_saturation.json`.
