# METHOD

## Claim
Learning proposes structured timing factor T; hard QP keeps feasibility and executable motion. First-round Z is frozen (`corridor-cost.json`).

## Timing training (formal route)
- **True Diff-QP**: active-set KKT implicit differentiation  
  `prototypes/time_fixed_z_qp/diff_time_qp_kkt.py`
- Loss: `L = J_traj/J_scale + λ_T * T/T_scale`  
  Scales from training pack only. Selected **λ_T = 0.1**.
- FD-proxy (`--grad fd`) is **ablation only**, not the final differentiable layer.
- CvxpyLayer full-matrix Parameter path was **rejected** (grads disagree with FD).

## Deployment (one-shot)
```
Observation → predict 1 T → rebuild real C(T) → corridor-cost top-1 Z → 1 hard QP
→ residual/freshness checks → append → publish → controller_first_use
```
Fallback is counted separately (`fallback=true`); not counted as one-shot success.

## Primary models
- Timing: `prototypes/time_fixed_z_qp/evidence/phase_f_train/timing_kkt_lam0.1_seed0.json`
- Z (frozen): `docker/dev-workspace/results/joint-time-v2/models/corridor-cost.json`
- Supervised baseline timing: `.../timing-schema2-regression.json`

## Z learning
Not enabled: one-shot failures are not dominated by wrong-Z (`fallback=0` on pilots). Phase H not triggered.
