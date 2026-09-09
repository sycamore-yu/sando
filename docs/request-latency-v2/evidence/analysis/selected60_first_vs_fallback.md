# Selected60: first fixed-assignment pass vs fallback

Assumptions: mid-technical reader; offline formal replay ≠ online publish clock.

Machine-readable twin: `selected60_first_vs_fallback.json`.

## Corpus

| Field | Value |
| --- | ---: |
| Formal runs | 5 (`run1_seed301` … `run5_seed305`; warmup `run0` excluded) |
| n_inputs (per method) | 300 |
| n_unique_requests | 60 |
| n_maps (unique `scene_id`) | 32 |
| n_strata | 6 |
| n_ref_feasible (offline original accept) | 45 / 60 |
| n_ref_feasible (capture `outcome_status==2`) | 35 / 60 |
| Candidate limit | **k=1** (`--candidate-limit 1`) |

Selection: `…/request-latency-v2/selection/selected60_manifest.json`.  
Replays: `…/request-latency-v2/stage6/replays/selected60/`.

## Classification

| Class | Meaning |
| --- | --- |
| `main_qp_accepted` | First non-fallback attempt accepted (original single attempt, or learned/previous first proposed QP **before** MIQP) |
| `fallback_then_accepted` | Main path failed; later fallback/MIQP accepted |
| `final_fail` | Nothing accepted |
| `infra_unsupported` | `model_missing` / unsupported formulation / cannot run AMPL / equivalent |

**Naming:** offline rate for class 1 is **first fixed-assignment problem pass rate**. Do **not** call blended accept **publish success**. The previously quoted ~75% accept is **final accept** = first-pass + fallback.

## Key table (selected60, pooled 5 formal runs)

| Method | n | supported | first_accept | fallback_accept | final_accept | final_fail | infra | first pass rate | fallback rate | final accept rate | attempts median | total_ms median | total_ms p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| original | 300 | 300 | 225 | 0 | 225 | 75 | 0 | **0.750** | 0.000 | 0.750 | 1 | 73.9 | 130.7 |
| bc | 300 | 300 | 200 | 25 | 225 | 75 | 0 | **0.667** | 0.083 | 0.750 | 1 | 53.3 | 76.8 |
| cost | 300 | 300 | 210 | 15 | 225 | 75 | 0 | **0.700** | 0.050 | 0.750 | 1 | 52.4 | 72.0 |
| previous | 300 | 300 | 210 | 15 | 225 | 75 | 0 | 0.700 | 0.050 | 0.750 | 2 | 52.9 | 508.4 |
| closed_loop | 300 | 0 | 0 | 0 | 0 | 0 | 300 | — | — | — | 1 | 73.6 | 126.7 |

`closed_loop`: all rows `fallback_reason=model_missing` → **infra_unsupported** (no closed-loop model on this campaign). Bare MIQP may still run; that is not a closed-loop first-proposal success.

## Latency by class (ms)

| Method | Class | n | median | p95 |
| --- | --- | ---: | ---: | ---: |
| original | main_qp_accepted | 225 | 78.3 | 148.9 |
| original | final_fail | 75 | 68.1 | 87.4 |
| bc | main_qp_accepted | 200 | 52.4 | 62.8 |
| bc | fallback_then_accepted | 25 | 76.8 | 85.7 |
| bc | final_fail | 75 | 54.0 | 65.0 |
| cost | main_qp_accepted | 210 | 51.4 | 62.2 |
| cost | fallback_then_accepted | 15 | 79.1 | 87.4 |
| cost | final_fail | 75 | 54.5 | 63.9 |

## Reading the old 75%

- **original:** 75% is entirely first-attempt (single original solve). No fallback path.
- **bc / cost:** final accept stays 75%, but **first fixed-assignment pass** is **66.7% (bc)** / **70.0% (cost)**; the rest of the accepts are **MIQP fallback** (8.3% / 5.0%).
- Same 75 final-fail complementary mass (25%) across original/bc/cost on this frozen set.

## selected12 diagnostic (keep separate; k=3)

Primary stage6 diagnostic: `…/replays/formal/run{1..5}_seed{101..105}.jsonl`, default **k=3** proposals (`candidate_limit` unset). Not the selected60 k=1 campaign.

| Method | n | first_accept | fallback_accept | final_accept | first pass rate | final accept rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| original | 60 | 40 | 0 | 40 | 0.667 | 0.667 |
| bc | 60 | 40 | 0 | 40 | 0.667 | 0.667 |
| cost | 60 | 40 | 0 | 40 | 0.667 | 0.667 |
| closed_loop | 60 | 0 | 0 | 0 | infra 60/60 | — |

On selected12, bc/cost fallbacks that ran did not accept (exhaust → fail); first-pass and final rates match.

## Source artifacts

- `docker/dev-workspace/results/request-latency-v3/analysis/selected60_first_vs_fallback.json`
- `docs/request-latency-v2/stage6-first-vs-fallback.md` (versioned summary)
