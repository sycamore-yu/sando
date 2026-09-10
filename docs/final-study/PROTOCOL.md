# PROTOCOL

## Offline
- Pack: `prototypes/time_fixed_z_qp/evidence/train16_pack_geometry.json`
- Train: `prototypes/time_fixed_z_qp/train_true_diff_timing.py`
- Eval: `prototypes/time_fixed_z_qp/eval_phase_e_oneshot.py`
- Failures stay in denominators; no fake gradients on infeasible QPs.

## Online pilots (Phase K)
- Script: `scripts/run_phase_k_pilots.sh`
- Seeds: **200–205** (frozen pilot set)
- Scene: `static_forest`, 50 obstacles, `dynamic_ratio=0`
- Setup: `/root/sando_ws/install-dev/setup.bash` (binary must live under `install-dev/sando/lib/sando/`)
- Methods compared so far: `supervised`, `true_diff` (+ `original` / `fd_proxy` as available)

## One-shot success (trajectory-level)
Exactly: `fallback=false` AND append AND publish AND `controller_first_use`.  
`goal_reached` is episode-level only.

## Freezes before wider test
Do not expand to 200–229 until Phase L Case A. Current decision: **Case B**.
