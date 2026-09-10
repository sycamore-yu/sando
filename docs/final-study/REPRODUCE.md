# REPRODUCE

## Host train (genesis env)
```bash
cd prototypes/time_fixed_z_qp
/home/tong/anaconda3/envs/genesis/bin/python train_true_diff_timing.py \
  --pack evidence/train16_pack_geometry.json \
  --init-model ../../docker/dev-workspace/results/joint-time-v2/models/timing-schema2-regression.json \
  --out-dir evidence/phase_f_train --steps 100 --seed 0 --lambda-t 0.1 --grad kkt
```

## Container online
```bash
# after rebuilding sando with SANDO_USE_AMPL=ON, sync binary:
cp -f /root/sando_ws/install-dev/lib/sando/sando /root/sando_ws/install-dev/sando/lib/sando/sando

TIMING=.../phase_f_train/timing_kkt_lam0.1_seed0.json \
  SEEDS=200 bash scripts/run_phase_g_oneshot.sh

METHODS="supervised true_diff" SEEDS="200 201 202 203 204 205" \
  TRUE_DIFF=.../phase_f_train/timing_kkt_lam0.1_seed0.json \
  bash scripts/run_phase_k_pilots.sh
```

## Key evidence paths
- Diff-QP: `prototypes/time_fixed_z_qp/evidence/diff_time_qp_kkt_probe0.json`
- Phase E/F: `prototypes/time_fixed_z_qp/evidence/phase_{e,f}_train/`
- Phase K: `docs/request-latency-v2/evidence/analysis/phase_k_pilots_compare.json`
- Live runs (gitignored workspace): `docker/dev-workspace/results/request-latency-v3/online/phase_k_pilots/`

## Phase M expand
```bash
bash scripts/run_phase_m_expand.sh
```
Freeze file: `docs/final-study/FREEZE.json`.
