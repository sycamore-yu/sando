# Fresh vs persistent runtime reuse (selected12)

Assumptions: you know offline replay JSONL, AMPL TRACE `import`/`update`, and accept = any attempt accepted.

## Protocol

- Input: `selected12.jsonl` (n=12)
- `--candidate-limit 1`, `SANDO_AMPL_TRACE=1`
- Arms: `--runtime-reuse fresh` (default) vs `persistent`
- Seeds: warmup 400; formal 401, 402 (warmup excluded from medians)
- Persistent keeps one AMPL Runtime per method across instances and sets `SANDO_AMPL_MODE=persistent`

## Process wall clock (full 12-instance run)

| run | seed | fresh_s | persistent_s | speedup |
|-----|------|---------|--------------|---------|
| warmup | 400 | 4.440 | 1.205 | 3.68x |
| formal1 | 401 | 4.630 | 1.209 | 3.83x |
| formal2 | 402 | 4.690 | 1.198 | 3.91x |

## TRACE import vs update (formal runs pooled)

| arm | import | update |
|-----|--------|--------|
| fresh | 120 | 34 |
| persistent | 10 | 144 |

Median TRACE slice (formal run1):

| arm/mode | compile_ms | prepare_ms | total_ms |
|----------|------------|------------|----------|
| fresh import | 35.66 | 12.08 | 53.98 |
| fresh update | 0.00 | 2.03 | 3.48 |
| persistent import | 31.74 | 10.12 | 44.61 |
| persistent update | 0.00 | 1.35 | 3.56 |

## Method total_ms median by tag (formal only)

| method | tag | fresh_ms | persistent_ms | speedup | accept fresh/pers |
|--------|-----|----------|---------------|---------|-------------------|
| original | success_slow | 99.1 | 15.5 | 6.41x | 1.000/1.000 |
| original | failure | 81.9 | 9.1 | 9.03x | 0.333/0.333 |
| bc | success_slow | 56.7 | 8.9 | 6.36x | 1.000/1.000 |
| bc | failure | 53.6 | 8.1 | 6.64x | 0.333/0.333 |
| cost | success_slow | 53.9 | 8.9 | 6.06x | 1.000/1.000 |
| cost | failure | 53.0 | 8.3 | 6.37x | 0.333/0.333 |

## Equivalence

- Accept agreement: **120/120**
- Objective agree when both accept (atol=2e-05): **80/80**
- Residuals agree when both accept (atol=1e-5): **80/80**
- Learned-method assignment agree (bc/cost/previous): **48/48**
- MIQP assignment diffs (original/closed_loop, multi-optima): 12 — accept/objective still match

## Verdict

- Persistent improves process wall clock: **True** (formal median speedup ≈ 3.87x)
- Accept unchanged: **True**
- Learned assignment/objective/residuals OK: **True**

