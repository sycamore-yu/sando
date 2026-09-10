# RQ1–RQ3 answers (plan2 scientific closeout)

Filled only after `FORMAL_AGGREGATE.json` + `FAILURE_ATTRIBUTION.json` exist.
Do not claim equivalence from equal counts; use Wilson / paired CI from `STATISTICS.md`.

## RQ1 — Learned one-shot vs Original

Question: On independent environments, does learned 1T+1Z+1QP improve latency / one-shot rate vs Original, and at what safety/task cost?

Evidence: paired Original vs Supervised/DiffOpt on formal groups.
Status: **PENDING formal matrix**

## RQ2 — DiffOpt vs Supervised

Question: Does DiffOpt (λ=1.0 KKT) beat supervised timing on closed-loop collision-free goal / latency / oneshot?

Evidence: paired Supervised vs DiffOpt, same Z, same online architecture.
Status: **PENDING formal matrix**

## RQ3 — Why (failure attribution)

Question: Are failures mostly timing-T, wrong-Z, map/sensing, optimizer, or execution/tracking?
Does wrong-Z dominate enough to restart Z learning? (`restart_Z_learning` in attribution JSON)

Evidence: `FAILURE_ATTRIBUTION.json`
Status: **PENDING formal matrix**; Z remains frozen unless wrong-Z dominates.

## Limitations (draft, refine after data)

- Formal N=30 per group × 3 groups; medium/hard dynamic not full matrix unless needed.
- Legacy forest 200–229 is repeated map — not used for map generalization claims.
- Original oneshot_append metric is structurally 0 (MIQP path); compare latency/task/safety fairly, not oneshot count against Original the same way.
