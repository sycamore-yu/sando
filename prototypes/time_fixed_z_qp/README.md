# Fixed-C / fixed-Z time-differentiable QP (stage 1)

Python Clarabel oracle + FD through hard QP, checked against live Gurobi rebuild.

## Reproduce

```bash
# Host (genesis env with cvxpy/torch)
cd prototypes/time_fixed_z_qp
python run_time_qp.py --fixture ../../tests/ampls/fixtures/translated_trajectory.json
python train_smoke.py --fixture ../../tests/ampls/fixtures/translated_trajectory.json

# Container (AMPL/Gurobi live rebuild)
source /root/sando_ws/src/sando/docker/dev_env.sh
./time_fixed_z_forward_probe \
  /root/sando_ws/src/sando/tests/ampls/fixtures/translated_trajectory.json 91659.8128
```

## Evidence (2026-09-09)

| Gate | Result |
| --- | --- |
| Native f Gurobi fixed-Z vs freezeAssignment | pass (`native_vs_frozen_ok`) |
| Python jerk vs Gurobi obj across feasible f | rel err ≤ 4e-6 (`data/forward_compare.json`) |
| FD dJ/df scales 1e-3/1e-4/1e-5 | stable (`data/python_fd_report.json`) |
| Trajectory-gradient updates f; frozen/stop do not | pass (`data/train_smoke_report.json`) |
