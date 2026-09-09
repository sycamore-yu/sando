# Fresh vs persistent AMPL runtime reuse

Assumptions: you know selected12 offline replay and that AMPL TRACE marks `import` vs `update`.

## What changed

`replay_integer_planning` gained `--runtime-reuse fresh|persistent` (default `fresh`).

- **fresh**: one `createRuntime()` per method per instance (current baseline; each method starts with AMPL import).
- **persistent**: one Runtime per method kept across input instances; forces `SANDO_AMPL_MODE=persistent` so later instances use native update (compile skipped on the update path).

JSONL metadata field `runtime_reuse` is `"fresh"` or `"persistent"`.

## selected12 result (k=1, 1 warmup + 2 formal)

| metric | fresh | persistent |
|--------|-------|------------|
| formal process wall (seed 401) | 4.63s | 1.21s |
| formal process wall (seed 402) | 4.69s | 1.20s |
| TRACE import/update (formal pooled) | 120/34 | 10/144 |
| bc median total_ms success_slow | 56.7 | 8.9 |
| bc median total_ms failure | 53.6 | 8.1 |
| accept agreement | 120/120 | same |

**Verdict:** persistent cuts process wall ≈ **3.9x** on this set **without changing accept**. bc/cost/previous assignments and objectives match (objective atol 2e-05). original/closed_loop show 12 MIQP multi-optima assignment diffs with matching accept/objective.

Full tables (gitignored): `docker/dev-workspace/results/request-latency-v3/analysis/fresh_vs_persistent.{json,md}`.

