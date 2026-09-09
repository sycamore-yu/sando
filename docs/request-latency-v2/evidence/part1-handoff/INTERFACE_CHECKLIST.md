# Part1 handoff — minimum interface checklist (from §5)

Source: `docs/fromchat/SANDO_3a13bf9_耗时归因续作与一次性规划验收.md` §5  
Consumer: Part2 latency / stage7–8 unlock  
Date: 2026-09-09  
Part2 tip: `3a13bf9` (+ pending verify/candidate/recreate fixes in tree)

## Goal reminder for both sides

Main chain per request: **one T → one full z → one main hard QP** → residual + freshness → append/publish.  
Fallback is a separate safety path; count main-one-shot success vs fallback success separately.

---

## I1 — Reconstructable planning observation

**Must include** (match real online corridor-builder inputs):

| Field group | Required content |
| --- | --- |
| Identity | `source_id`, `config_id`, `scene_id`, `episode_id`, `request_id`, content hash of observation |
| States | local start / goal (`local_E` 9-vector), `t0`, `planning_start_time`, `observation_time` |
| Time base | `n`, `initial_dt`, `dc`, original factor / segment_dt |
| Dynamics | `v_max`, `a_max`, `j_max`, jerk smooth weight, environment assumption |
| Geometry inputs | raw path vertices into decomp, request-level obstacle estimates (pose+size+stamp), occupy/unknown grid semantics |
| Map | frame, resolution, origin, inflate/filter state; **actual** `visible_map` (or proven-minimal equivalent) |

**Acceptance**

1. Same observation identity + hash reused across all query times for one request.  
2. Empty legacy fields stay empty (do not invent voxels).  
3. Dynamic obstacles = **request-time estimates**, not world-file ground truth (GT is a separate eval domain).

**Unlocks:** multi-T rebuild, stage7 fixed-f retarget, stage8 enumeration.

**Current gap (Part2 measured):** even with `obstacles.json` sidecars, new-f queries still miss `visible_map`, `global_path`, `v_max`, `a_max`, `j_max` on validation snapshots.

---

## I2 — Real new-time queryer

Replace “same-factor copy outcome / new-factor status-only” with **actual corridor build + solve**.

**Input:** frozen request, target factor, optional reference assignment, fixed budget (main z ≤1, main QP ≤1).  
**Output:** observation id, time/layer bounds, geometry id, full assignment, model id, solve status, original objective, recovered trajectory, original residuals, all attempts + wall times.

**Implementation rule:** reuse C++ online geometry + problem construction; Part2 consumes the same binary/API.

**Acceptance order**

1. New complete snapshot: rebuild+solve at **original** factor — match objective, residuals, trajectory (or objective/feasibility equivalence).  
2. Then query `1.37` and frozen grid `[1.0,1.25,…,2.5]`.  
3. Old incomplete snapshots keep regression expectation `blocked_missing_observation`.  
4. New output round in a **new** directory; old small-table stays read-only.

**Unlocks:** stage7 `time_only` / `joint` offline arms; stage8 multi-T labels.

---

## I3 — Model handoff (three tiers)

Each artifact needs: file path, **sha256**, format, input order/semantics, time range, `n`, normalization, parent model id, train data+seeds, validation selection, online parity result.

| Tier | What | Part2 use when received |
| --- | --- | --- |
| T1 | Fixed / compatible single-output time model | Wiring + protocol check |
| T2 | Trainable independent time model + corridor model | Independent-parameter combo preflight |
| T3 | Shared encoder + conditional dual heads | Final main-structure stage7/8 |

**Unlock rule:** first delivered tier unlocks its engineering checks immediately; T3 performance claims need independent eval scenes.

---

## Part2 will do after each delivery

1. Record model/observation hashes under `request-latency-v3/`.  
2. Run corresponding stage7 arm(s) under frozen budget (1 time, 1 z, 1 main QP).  
3. Keep fallback metrics separate; never fold into one-shot success.  
4. Failures/cancels/retries retained.

## Contact artifacts

- Part2 status: `docs/request-latency-v2/STATUS.md`  
- Execution plan: `docs/request-latency-v2/EXECUTION_PLAN.md`  
- This checklist copy: `docker/dev-workspace/results/request-latency-v3/part1-handoff/INTERFACE_CHECKLIST.md`
