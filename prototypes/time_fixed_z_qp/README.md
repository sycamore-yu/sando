# Fixed-C / fixed-Z time-differentiable QP (stage 1)

Python Clarabel oracle + FD through hard QP, checked against live Gurobi rebuild.

## Reproduce

```bash
# Host (conda env genesis: cvxpy, torch)
cd prototypes/time_fixed_z_qp
python run_time_qp.py --fixture ../../tests/ampls/fixtures/translated_trajectory.json
python train_smoke.py --fixture ../../tests/ampls/fixtures/translated_trajectory.json

python train_time_nn_qp.py pack \
  --selected60 ../../docker/dev-workspace/results/request-latency-v2/stage6/inputs/selected60.jsonl \
  --replay ../../docker/dev-workspace/results/request-latency-v2/stage6/replays/selected60/run1_seed301.jsonl \
  --out evidence/train16_pack_geometry.json --n 16
python train_time_nn_qp.py train \
  --pack evidence/train16_pack_geometry.json \
  --init-model ../../docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json \
  --out-dir evidence/train16_run --steps 100 --lr 1e-3 --seed 0

# Container AMPL/Gurobi live rebuild
source /root/sando_ws/src/sando/docker/dev_env.sh
./time_fixed_z_forward_probe \
  /root/sando_ws/src/sando/tests/ampls/fixtures/translated_trajectory.json 91659.8128
```

## Evidence (2026-09-09)

| Gate | Result |
| --- | --- |
| Native f Gurobi fixed-Z vs freezeAssignment | pass |
| Python jerk vs Gurobi obj (feasible f) | rel err ≤ 4e-6 |
| FD dJ/df @ 1e-3/1e-4/1e-5 | stable |
| Scalar f trajectory-gradient update | pass |
| Timing MLP 16×100 QP grads seed0 | mean J/J_scale 0.279→0.190 |
