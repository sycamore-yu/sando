# 06 Results

Formal closed-loop A/B/C on independent environments (270 paired episodes).

## Tables / figures

- `final/TABLE_MAIN.md`
- `final/TABLE_LATENCY.md`
- `final/TABLE_SAFETY.md`
- `final/TABLE_ABLATION.md`
- `final/FIG_*_DATA.json`
- `final/FAILURE_ANALYSIS.md`

## Aggregates

- `FORMAL_AGGREGATE.json` — rates, Wilson 95% CIs, latency medians
- `PAIRED_BOOTSTRAP.json` — paired Δ with bootstrap 95% CIs
- `FAILURE_ATTRIBUTION.json` — buckets; `restart_Z_learning: false`

## Scientific read

See `00_EXECUTIVE_SUMMARY.md` and `RQ_ANSWERS.md`.

Headline only: learned one-shot **cuts latency** and delivers **oneshot appends**; **does not** improve geometry-aware collision-free success; DiffOpt **does not** beat Supervised online on these tests; **do not restart Z**.
