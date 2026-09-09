# Stage 6: first fixed-assignment pass vs fallback (selected60)

Assumptions: mid-technical reader; offline formal replay clocks ≠ online publish.

Full tables (gitignored): `docker/dev-workspace/results/request-latency-v3/analysis/selected60_first_vs_fallback.{json,md}`.

## Setup

- Inputs: selected60 formal replays `run{1..5}_seed{301..305}` (`--candidate-limit 1`); warmup `run0` excluded.
- Corpus: n_inputs=300/method, n_unique_requests=60, n_maps=32, n_ref_feasible offline original=45/60 (capture status==2: 35/60).
- Classes: `main_qp_accepted` | `fallback_then_accepted` | `final_fail` | `infra_unsupported`.

**Naming:** rate for `main_qp_accepted` = **first fixed-assignment problem pass rate**. Do **not** call blended accept **publish success**.

## Key results (original / bc / cost)

| Method | first_accept | fallback_accept | final_accept | final_fail | first pass rate | fallback rate | final accept rate | total_ms med / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| original | 225 | 0 | 225 | 75 | **0.750** | 0.000 | 0.750 | 73.9 / 130.7 |
| bc | 200 | 25 | 225 | 75 | **0.667** | 0.083 | 0.750 | 53.3 / 76.8 |
| cost | 210 | 15 | 225 | 75 | **0.700** | 0.050 | 0.750 | 52.4 / 72.0 |

The earlier “75% accept” on selected60 is **final accept** (any accepted attempt). For bc/cost that blends first-pass QP with MIQP fallback; first-pass alone is 66.7% / 70.0%.

Also present: `previous` matches cost rates (0.700 / 0.050 / 0.750); `closed_loop` is 300/300 `infra_unsupported` (`model_missing`).

## selected12 vs selected60

| Set | Role | k (proposals) | Notes |
| --- | --- | ---: | --- |
| selected12 | primary stage6 diagnostic | 3 (default) | formal `run{1..5}_seed{101..105}`; bc/cost first=final=0.667 (fallbacks ran but did not accept) |
| selected60 | expansion formal campaign | 1 | this split; final accept 0.750 with fallback contribution on bc/cost |

Do not merge k=3 and k=1 pass-rate numbers without labeling k.
