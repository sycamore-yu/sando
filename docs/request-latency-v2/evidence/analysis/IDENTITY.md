# Identity sheet (gate 12)

- Branch: `feat/ampl-gurobi` → remote `personal/feat/ampl-gurobi`
- Plan: `docs/unified-plan.md`
- Final table: `docs/request-latency-v2/evidence/analysis/final_latency_task_table_seed200.json`

## Models
- Timing QP-trained seed0: `prototypes/time_fixed_z_qp/evidence/train16_run/timing_qp_seed0.json`
- Timing supervised: `docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json`
- Corridor cost: `docker/dev-workspace/results/joint-time-v2/models/corridor-cost.json`

## Key commits
- Endpoint snap fix: `2859980`
- Gate7 online confirm docs: `37ace79`
- Gate8 docs: `361063b`

## Reproduce (docker `sando-dev`)
```bash
source /root/sando_ws/src/sando/docker/dev_env.sh
# rebuild
colcon build --packages-select sando --build-base build-dev --install-base install-dev --paths src/sando
# original smoke
bash docker/dev-workspace/results/request-latency-v3/failures/run_smoke_seed200_post_snap.sh
# oneshot QP-timing
# see run_oneshot_gate8.sh / run_oneshot_supervised_seed200.sh
```
