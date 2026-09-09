# 0008 — Request time boundaries, same-budget attribution, two-task interface

Status: Accepted for measurement protocol (2026-09-09). Performance change for unused update-path compile is landed; joint-model interface still owned by Part1.

## Decision

1. Keep `total_ms` as replan enter → metrics emit after cancel-drain + append (excludes publish).
2. Add dedicated fields: `usable_ms` (first winner before drain), `reclaim_ms` (after drain + solver recreate), publish as a second JSONL event `kind=publish` with `publish_ms`.
3. Report latency (critical path) and workload (sum of factor/attempt work) separately; parallel overlap must use real overlap, not sum-as-latency.
4. Part2 owns timing, benchmarks, stats, geometry event review. Part1 owns models, training, time gradient, reconstructable queryer.
5. Same-budget arms freeze `main_time_proposals=1` and `main_assign_outputs=1`; original multi-factor search remains a separately budgeted ANCHOR.

## Alternatives

- Fold publish into `total_ms` — rejected (breaks historical semantics).
- Permanent AMPL compiler process — deferred pending license/equivalence design.
- Equating offline single-factor replay ms with online `parallel_ms` — rejected.

## Correctness bounds

- Hard residual checks remain the accept gate for published trajectories.
- Forest AABB overlaps stay conservative vs cylinder geometry; report separately from contact.
- Update-path export/compile skip is valid only because `updateNative` consumes the snapshot, not the NL; audit mode still exports/compiles.

## Acceptance

- Stage6 formal selected12 replay + TRACE overhead ≤3% + before/after compile-skip.
- Stage7 partial offline arms; time_only/joint blocked on Part1 interfaces.
- Stage8 backfill list frozen for Part1 queryer; new-model verify blocked until Part1 publishes model identity.

## Close path

When Part1 delivers reconstructable multi-T queryer + new model sha256, Part2 re-runs stage7 arms under this ADR and closes remaining blockers in `request-latency-v2/stage7/failures/blockers.json`.
