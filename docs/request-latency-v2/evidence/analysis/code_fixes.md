# Code fixes (§3.1–3.3)

Date: 2026-09-09

## Files changed

| Area | File | Change |
| --- | --- | --- |
| A | `src/sando/ampls_runtime.cpp` | `need_export_compile = !updating \|\| audit \|\| verify_updates_enabled`; reuse verify flag for `verifyUpdate` |
| A | `tests/ampls/persistent_probe.cpp` | Cover first import, normal update, update+verify (audit off), audit+verify, infeasible under verify |
| B | `src/sando/replay_integer_planning.cpp` | Capacity check before append in `first_candidates`; `parse_positive_size`; CLI overrides env (comment) |
| B | `src/sando/gurobi_solver.cpp` | Same capacity-before-append + dedupe on Previous/Learned corridor paths |
| B | `tests/ampl_model/test_integer_replay.cpp` | Previous at first/middle/last; missing/invalid; limits 1/3; parse reject 0/neg/junk/overflow; CLI>env |
| B/C | `tests/ampls/online_corridor_probe.cpp` | Online previous-path limits; recreate contract keeps `candidate_limit==1` |
| C | `src/sando/sando.cpp` | After solver-error recreate, re-apply candidate limit, corridor policy/method, threads (shared resolve helper) |

AMPL auth / AMPLS object lifecycle unchanged.

## Tests run

After `make -C docker dev-build` (succeeded):

```
ctest -R 'ampl_persistent_updates|integer_replay_methods|online_corridor_candidates'
```

Results (with `docker/dev_env.sh` sourced):

| Test | Result |
| --- | --- |
| `integer_replay_methods` | Passed (0.04s) |
| `online_corridor_candidates` | Passed (0.59s) |
| `ampl_persistent_updates` | Passed (0.15s) |

Cancel paths already covered by existing online/preflight probes; not duplicated here.

## Blockers

None.
