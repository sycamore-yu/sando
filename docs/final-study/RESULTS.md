# RESULTS

## Offline pack16 (fixed Z from pack assignment)

| Method | Accept | Rate | Mean jerk (accepted) | Mean T |
|---|---:|---:|---:|---:|
| capture_factor oracle | 16/16 | 1.000 | 88365 | 1.42 |
| supervised_init | 15/16 | 0.938 | 51431 | 1.51 |
| true-diff KKT λ=0 / λ=0.1 | 14/16 | 0.875 | ~19k | ~1.8 |
| FD-proxy λ=0 | 14/16 | 0.875 | ~19k | ~1.9 |

Evidence: `prototypes/time_fixed_z_qp/evidence/phase_{e,f}_train/offline_oneshot_compare.json`.

## Online pilots seeds 200–205 — static_forest

| Method | Task success | Mean P50 ms | Failures kept |
|---|---:|---:|---|
| A Original SANDO | 6/6 | 38.6 | none |
| B Supervised one-shot | 6/6 | 24.0 | none |
| C FD-proxy one-shot | 5/6 | 21.8* | seed203 timeout |
| D True Diff-QP λ=0.1 | 5/6 | 21.7 | seed201 timeout |

\*includes failed seed’s low P50 in mean; successes ≈24.4–25.0 ms.

Evidence: `docs/request-latency-v2/evidence/analysis/phase_k_pilots_compare.json`.

## Online pilot — unknown_dynamic (ratio 0.65), seeds 200–201

| Method | Task success | Approx P50 ms |
|---|---:|---:|
| Supervised | 2/2 | ~69 |
| True Diff-QP | 2/2 | ~75 |

Evidence: `docs/request-latency-v2/evidence/analysis/phase_k_unknown_dynamic_pilots.json`.

True-diff **λ=1.0** unknown_dynamic 200–201: **2/2** success (P50≈78–80 ms). Evidence: `phase_l_caseb_lam1_unknown_dynamic.json`.

## Phase L
**Case B** initially (λ=0.1: 5/6 vs supervised 6/6, T saturates).

**Mitigation:** λ_T=1.0 model → **6/6** on seeds 200–205; F_MAX fraction ~11–22%; P50≈24.2 ms.  
Evidence: `phase_l_case_b_lam1_mitigation.json`. Candidate to promote as primary timing model (still freeze before any 200–229 expand).
