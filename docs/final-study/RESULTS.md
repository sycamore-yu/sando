# RESULTS

## Offline pack16 (fixed Z from pack assignment)

| Method | Accept | Rate | Mean jerk (accepted) | Mean T |
|---|---:|---:|---:|---:|
| capture_factor oracle | 16/16 | 1.000 | 88365 | 1.42 |
| supervised_init | 15/16 | 0.938 | 51431 | 1.51 |
| true-diff KKT λ=0 (Phase F) | 14/16 | 0.875 | ~19038 | ~1.89 |
| true-diff KKT λ=0.1 (Phase F) | 14/16 | 0.875 | ~19149 | ~1.77 |
| FD-proxy λ=0 | 14/16 | 0.875 | ~19042 | ~1.87 |

Evidence: `prototypes/time_fixed_z_qp/evidence/phase_e_train/offline_oneshot_compare.json`, `phase_f_train/offline_oneshot_compare.json`.

## Online pilots seeds 200–205 (static_forest, 50 obs)

Frozen Z: `corridor-cost.json`. One-shot path with controller_first_use instrumentation.

| Method | Task success | Goal reached | Mean P50 ms | Mean P95 ms | Failures kept |
|---|---:|---:|---:|---:|---|
| Supervised one-shot | 6/6 | 6/6 | 24.0 | 33.0 | none |
| True Diff-QP λ=0.1 | 5/6 | 5/6 | 21.7 | 29.7 | seed201 timeout (20 oneshot appends) |

Evidence: `docs/request-latency-v2/evidence/analysis/phase_k_pilots_compare.json`.

### Phase G seed200 probe (true-diff Phase E model)
goal_reached; 956 oneshot appends; 956 controller_first_use; fallback=0.

## Phase L decision
**Case B**: true-diff ≈/not clearly better than supervised on task success (5/6 vs 6/6) despite slightly lower planning latency. Do **not** expand to 200–229 yet. Attribution: online T often saturates at F_MAX=2.5; train/test feature gap; one retained timeout failure.

Original SANDO and FD online arms: in progress / pending merge into this table.
