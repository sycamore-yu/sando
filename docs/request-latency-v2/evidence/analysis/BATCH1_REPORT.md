# Batch 1 report — continuation after 3a13bf9

## Completed

1. **Selected60 first vs fallback split** — final 75% accept ≠ first-proposal pass (bc first 66.7%, fallback 8.3%; cost first 70%, fallback 5%).
2. **Compile-skip + VERIFY_UPDATES compatible** — export/compile when verify on.
3. **Previous-assignment candidate overflow fixed** — capacity check before append; limit=1 safe.
4. **Solver recreate re-applies candidate limit/policy/threads**.
5. **Fresh vs persistent reuse** — accept unchanged; process wall ~3.9× faster persistent.
6. **Forest cylinder proxy** — 3 flights; AABB-only conservative hits found; first AABB can be cylinder-miss.
7. **Part1 §5 interface checklist** delivered.

## Acceptance

| Gate | Result |
|------|--------|
| Split denominators clear | pass |
| Code fixes + targeted ctest | pass (`integer_replay_methods`, `online_corridor_candidates`, `ampl_persistent_updates`) |
| Cylinder proxy on odom | pass (discrete samples) |
| Online 4-scene full timing | **partial / blocked** — see below |

## Online timing status

- Protocol: `config/online_timing_dev4.json` (easy/medium forest + ud50/ud100; original vs cost; `SANDO_CORRIDOR_CANDIDATE_LIMIT=1`).
- install-dev smoke (`smoke_static_easy`): metrics present, **candidate_limit=1 confirmed**, but **goal not reached** (odom≈1 sample, robot stuck at start) → rc=2. Timing fields emitted (`usable_ms` stayed 0 because no winner/append).
- Campaign retries retained under `online.cancelled_*` / `failures/`.

## Real blockers

1. **install-dev online flight unhealthy** (no motion) — need bisect vs frozen `install/` binary and Part1 WIP on `sando.cpp` / HGP.
2. **Part1 I1–I3** still required for stage7 time_only/joint and stage8 multi-T.
3. First AABB **event-time** alignment still missing co-sampled streams.

## Result locations

- `docker/dev-workspace/results/request-latency-v3/`
- Docs: `docs/request-latency-v2/{EXECUTION_PLAN,STATUS,PART1_INTERFACE_CHECKLIST,stage6-first-vs-fallback,stage6-forest-cylinder-proxy,fresh-vs-persistent}.md`

## Next operation

1. Bisect install-dev online no-motion (compare frozen install smoke).
2. Finish 8-flight online campaign once motion works.
3. Await Part1 I1/I2/I3 deliveries → unlock stage7/8 remaining arms.
