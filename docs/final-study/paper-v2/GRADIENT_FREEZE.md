# Gradient correctness freeze (plan2 Phase 5)

Authority: `docs/fromchat/plan2.md` §10  
Evidence: `prototypes/time_fixed_z_qp/evidence/phase5_grad_validation_pack30.json`

## Protocol

- Path: active-set KKT implicit differentiation (`diff_time_qp_kkt.py`)
- FD oracle scales: `1e-3`, `1e-4`, `1e-5` (oracle only; not used for training)
- Pack: first 30 Clarabel-feasible items from `parity50_pack.json` (static_forest + unknown_dynamic)

## Results

| Metric | Value |
|---|---|
| Candidates | 30 |
| Smooth objective-grad pass (`autograd_vs_fd_ok`) | **30 / 30** |
| Full pass (grad + solution probe) | **29 / 30** |
| Failed solution probe | 1 (`unknown_dynamic-n100-d0.65-seed100`, index 10) |

KKT gradients are frozen as the training path. FD remains oracle-only.
