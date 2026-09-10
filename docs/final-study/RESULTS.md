# RESULTS

## Offline pack16 (fixed Z from pack assignment)

| Method | Accept | Rate | Mean jerk (accepted) | Mean T |
|---|---:|---:|---:|---:|
| capture_factor oracle | 16/16 | 1.000 | 88365 | 1.42 |
| supervised_init | 15/16 | 0.938 | 51431 | 1.51 |
| true-diff KKT λ=0 / λ=0.1 | 14/16 | 0.875 | ~19k | ~1.8 |
| FD-proxy λ=0 | 14/16 | 0.875 | ~19k | ~1.9 |

Evidence: `prototypes/time_fixed_z_qp/evidence/phase_{e,f}_train/offline_oneshot_compare.json`.

## Online pilots seeds 200–205 — static_forest (50 obstacles)

| Method | Task success | Mean P50 ms | Failures kept |
|---|---:|---:|---|
| A Original SANDO | 6/6 | 38.6 | none |
| B Supervised one-shot | 6/6 | 24.0 | none |
| C FD-proxy one-shot | 5/6 | 21.8* | seed203 timeout |
| D True Diff-QP λ=0.1 | 5/6 | 21.7 | seed201 timeout |
| E True Diff-QP λ=1.0 (frozen) | 6/6 | 24.2 | none |

\*includes failed seed’s low P50 in mean.

Evidence: `phase_k_pilots_compare.json`, `phase_l_case_b_lam1_mitigation.json`.

## Phase M formal expand — static_forest seeds 200–229 (frozen λ=1.0)

| Method | Task success | Mean P50 ms | Failures kept |
|---|---:|---:|---|
| Supervised one-shot | 29/30 | 23.5 | seed226 timeout |
| True Diff-QP λ=1.0 | 29/30 | 23.5 | seed201 timeout |

Evidence: `docs/request-latency-v2/evidence/analysis/phase_m_expand_200_229.json`.

**Read:** after Case B mitigation, true-diff **matches** supervised on the frozen formal split (tied latency and success). Failures retained.

## Online — unknown_dynamic (ratio 0.65)

| Method | Seeds | Task success | Approx P50 ms |
|---|---|---:|---:|
| Supervised | 200–201 | 2/2 | ~69 |
| True Diff-QP λ=0.1 | 200–201 | 2/2 | ~75 |
| True Diff-QP λ=1.0 | 200–201 | 2/2 | ~78–80 |

Evidence: `phase_k_unknown_dynamic_pilots.json`, `phase_l_caseb_lam1_unknown_dynamic.json`.

## Dense obstacle (100 trees) — seeds 200–205

| Method | Task success | Mean P50 ms | Failures kept |
|---|---:|---:|---|
| Supervised | 6/6 | 23.9 | none |
| True Diff-QP λ=1.0 | 5/6 | 20.8 | seed201 timeout |

Evidence: `docs/request-latency-v2/evidence/analysis/phase_m_dense100.json`.

## Episode quality (Phase M expand, successful episodes)

| Method | Mean wall s | Mean goal dist m | Mean tracking RMSE m |
|---|---:|---:|---:|
| Supervised | 45.3 | 0.238 | 0.0032 |
| True Diff-QP λ=1.0 | 48.1 | 0.242 | 0.0027 |

Evidence: `phase_m_episode_quality.json`.  
Note: co-sampled AABB “collision” flags fire on nearly all successful episodes for **both** methods (often obstacle id `21`) — known forest cylinder/AABB metric limitation; not treated as method-specific safety regression.

## Phase L
Initial Case B (λ=0.1 saturation) → mitigated by λ=1.0 → freeze → Phase M expand.  
**Conclusion:** optimizer-trained timing with λ_T=1.0 is **competitive with supervised** on the frozen formal split (29/30 vs 29/30); Original remains slower (~39 ms P50). Not a clear win over supervised on task success; attribution documented.
