# Request-latency stages 6–8 execution plan

## Identity

- Branch: `feat/ampl-gurobi` → `personal/feat/ampl-gurobi`
- Measurement base: `ce09ee3…` (+ later commits for instrumentation / candidate-limit)
- Results root (gitignored): `docker/dev-workspace/results/request-latency-v2/`
- Dev image: `sando-integer-centered:20260907`

## Entrypoints

```bash
make -C docker dev-status
make -C docker dev-build
make -C docker dev-test
# inside sando-dev after source docker/dev_env.sh:
replay_integer_planning --input …/selected12.jsonl --output out.jsonl \
  --bc …/bc.json --cost …/cost.json --seed 101 --candidate-limit 1
```

## Frozen thresholds

See `docker/dev-workspace/results/request-latency-v2/config/stage6_thresholds.json` and
`stage7/config/frozen_protocol.json` (f=2.0, main time/assign = 1).

## Stage checklist

| Item | Owner | Gate |
|------|-------|------|
| Timing boundaries usable/publish/reclaim | Part2 | code + metrics schema |
| Selected12 / Selected60 same-state replay | Part2 | JSONL + TRACE |
| Compile-skip on update | Part2 | before/after accept agreement |
| Same-budget 4 arms | Part2+Part1 | time_only/joint need multi-T rebuild |
| Backfill list | Part2 | `stage8/backfill_list.json` |
| Multi-T queryer fill | Part1 | observation-complete snapshots |
| New model train + id | Part1 | sha256 under agreed path |
| Freeze compare re-run | Part2 | stage7 protocol |

## Recovery

If AMPL missing: `source /root/sando_ws/src/sando/docker/dev_env.sh` inside container.
If `dev-build` exit 71: sources changed mid-build — rebuild once tree is quiet.
