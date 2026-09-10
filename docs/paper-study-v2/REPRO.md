# Reproducibility package (plan2 §20)

Fill SHA/hashes at freeze time; do not retune after formal test start.

## Commit / models

| Item | Value |
|---|---|
| Research baseline | `1e4f9f918113857026a9d3b406c6a6209b9b8ff8` |
| Formal freeze file | `docs/paper-study-v2/FREEZE.json` |
| DiffOpt timing (λ=1.0) | `prototypes/time_fixed_z_qp/evidence/phase_e_train/timing_kkt_lam1.0_seed0.json` |
| Supervised timing | `docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json` |
| Corridor Z | `docker/dev-workspace/results/joint-time-v2/models/corridor-cost.json` |

## Environment

- Manifest: `docs/paper-study-v2/environment_manifest.json`
- Audit: `docs/paper-study-v2/ENVIRONMENT_AUDIT.md`
- Formal groups: `procedural_static_easy`, `procedural_static_medium`, `unknown_dynamic_easy`

## Commands

```bash
# Inside sando-dev with docker/dev_env.sh sourced
GROUP=procedural_static_easy METHODS="original supervised true_diff" \
  OUT_ROOT=.../paper_procedural_static_easy bash scripts/run_paper_formal.sh

# Aggregate
python3 scripts/aggregate_paper_formal.py \
  docker/dev-workspace/results/request-latency-v3/online/paper_procedural_static_easy \
  docker/dev-workspace/results/request-latency-v3/online/paper_unknown_dynamic_easy \
  docker/dev-workspace/results/request-latency-v3/online/paper_procedural_static_medium \
  --out docs/paper-study-v2/FORMAL_AGGREGATE.json

python3 scripts/attribute_paper_failures.py \
  docker/dev-workspace/results/request-latency-v3/online/paper_procedural_static_easy \
  docker/dev-workspace/results/request-latency-v3/online/paper_unknown_dynamic_easy \
  docker/dev-workspace/results/request-latency-v3/online/paper_procedural_static_medium \
  --out docs/paper-study-v2/FAILURE_ATTRIBUTION.json
```

## Raw evidence roots

`docker/dev-workspace/results/request-latency-v3/online/paper_{group}/{method}/seed*/`

## Method / safety / QP / grad evidence

See `IDENTITY_CHAIN.md`, `SAFETY_METRIC.md`, `QP_EQUIVALENCE_AUDIT.md`, `GRADIENT_FREEZE.md`, `STATISTICS.md`.
