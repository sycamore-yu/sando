# Stage 6 hypothesis evidence (§3.5 items 1–7)

Assumptions: you know stage6 selected12 offline replay vs online capture clocks, and that AMPL TRACE lines split export/compile/prepare/solve.

Versioned summary of `docker/dev-workspace/results/request-latency-v2/stage6/analysis/hypotheses.json`.  
Primary diagnostic set remains **selected12** (default **k=3** proposals). **selected60** is the expansion set and **has been formally replayed** with **`--candidate-limit 1`** (`run{1..5}_seed{301..305}`); first-pass vs fallback split is in `docs/request-latency-v2/stage6-first-vs-fallback.md` (results under `request-latency-v3/analysis/`). Keep k=3 and k=1 numbers separate.

| ID | Claim | Evidence status |
| ---: | --- | --- |
| 1 | Correct candidate ranked late → extra fixed-assignment solves | partial |
| 2 | AMPL compile / model prepare dominate; repeats amplify | confirmed |
| 3 | Solver vs process start vs locks / contention shares | partial |
| 4 | Main proposal failure stacks full original search → long tail | partial |
| 5 | After first success, cancel/reclaim keep blocking | blocked |
| 6 | Fewer time candidates vs better time prediction | blocked |
| 7 | Cold start / model reuse / sim load change conclusions | partial |

## 1. Late correct candidate → extra solves

- **Observed fact (selected12, k=3):** bc/cost median `n_attempts` = 1 on `success_slow`, = 4 on `failure`; failure fallback share 0.67 with `fallback_ms` median ~37–39 ms. `ranking_ms` ~2.5 ms on both tags.
- **Observed fact (selected60, k=1):** first fixed-assignment pass rate bc **0.667** / cost **0.700**; fallback-then-accept **0.083** / **0.050**; blended final accept **0.750** (same as original). See `stage6-first-vs-fallback.md`.
- **Possible explanation:** Several fixed-assignment QPs run before accept/fallback; early ranks may be infeasible. No oracle of “first correct rank” in this corpus.
- **Verification experiment:** Log per-attempt feasibility vs offline oracle assignments on the frozen corridor; measure how often first feasible is rank>1.
- **Status:** partial

## 2. AMPL compile / prepare dominate

- **Observed fact:** TRACE `compile_share_median` ≈ 0.678; `solve_share_median` ≈ 0.018 (555 segments). Skip unused update compile: update compile 27.4→0 ms, update total 32.9→1.3 ms; campaign wall median ≈ −20%; accept agreement 100%.
- **Possible explanation:** Each attempt imports/updates AMPL; compile was paid on updates that never needed NL export. Multi-attempt paths multiply that cost.
- **Verification experiment:** Done via `before_after_skip_compile.json`; optional repeat on selected60.
- **Status:** confirmed

## 3. Solver vs start vs locks / contention

- **Observed fact:** Adapter share median ≈ 0.84–0.88; solve median ≈ 0.64 ms. Online `cancel_drain` / usable / publish / reclaim unavailable for selected12.
- **Possible explanation:** Offline walls are mostly adapter work. Spawn, locks, and online contention not isolated here.
- **Verification experiment:** Add start/lock spans; recapture with full `replan_metrics`; contention on/off pairs.
- **Status:** partial

## 4. Failure stacks original search → long tail

- **Observed fact (selected12, k=3):** bc/cost failures ~133–185 ms with 4 attempts + fallback; success_slow ~45–59 ms / 1 attempt. Capture `parallel_optimization_ms` ~391–2805 ms ≫ offline totals.
- **Observed fact (selected60, k=1):** when first QP fails but MIQP accepts, bc/cost fallback-accept latency median ~77–79 ms vs first-accept ~51–52 ms; final_fail still ~54–55 ms median (no long stacked QP chain under k=1).
- **Possible explanation:** Failed proposals add QP attempts and MIQP fallback; online also pays multi-factor parallel and drain.
- **Verification experiment:** Phase-split walls on a full-metrics recapture of the same IDs.
- **Status:** partial

## 5. Cancel / reclaim after first success

- **Observed fact:** `n_full_online_metrics=0` for selected12; cancel-drain share undefined (`metrics:null` capture).
- **Possible explanation:** Drain after a winning factor may still block online critical path — unmeasured.
- **Verification experiment:** Recapture with `cancel_drain_ms`, `usable_ms`, `reclaim_ms`, publish events.
- **Status:** blocked

## 6. Fewer time candidates vs prediction quality

- **Observed fact:** Formal replay freezes one factor/corridor; cannot separate candidate count from predictor quality.
- **Possible explanation:** Online gains from timing policies may be mostly fewer proposals; unseparated in stage6.
- **Verification experiment:** Same-budget single- vs multi-candidate arms (stage7-style) on selected12/60.
- **Status:** blocked

## 7. Cold start, reuse, parallel load

- **Observed fact:** Warmup excluded; TRACE overhead ≈ 0% (≤3% pass). Skip-compile changes walls without changing accepts. No controlled contention sweep on selected12.
- **Possible explanation:** TRACE/warmup not first-order; compile-on-update was. Host contention still unknown for online tails.
- **Verification experiment:** Cold vs warm and exclusive vs contended campaigns on the same inputs.
- **Status:** partial

## Source artifacts

- `stage6/analysis/formal_replay_summary.json` (selected12)
- `stage6/analysis/formal_replay_rows.jsonl` (selected12)
- `stage6/analysis/selected60_summary.json` (blended accept/latency only)
- `../request-latency-v3/analysis/selected60_first_vs_fallback.json` (first vs fallback split)
- `docs/request-latency-v2/stage6-first-vs-fallback.md`
- `stage6/analysis/before_after_skip_compile.json`
- `stage6/analysis/online_critical_path_selected12.json`
- `stage6/analysis/trace_overhead.json`
- `stage6/analysis/hypotheses.json`
