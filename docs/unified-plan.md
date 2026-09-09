# SANDO unified plan（唯一总计划 · Ultimate Goal 模式）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
Engineering Baseline：`103faa1`  
权威长期任务书：`docs/fromchat/plan.md`

---

## Ultimate Goal

Learning proposes structured T/Z; hard QP keeps feasibility and executable motion;
optimizer-derived trajectory/task loss trains the learned decisions.
Deployed path is exactly **1T → real C(T) → 1Z → 1 hard QP** (fallback counted separately).

Stop and report “All done” **only** when `docs/fromchat/plan.md` §3 is fully evidenced.

---

## Current Milestone

**Phase F — Expand timing training (100 updates, 3 seeds) → then Phase K pilots 200–205**

---

## Completed Evidence

### Milestone 0 / Phase I engineering baseline
旧 Gate 1–12 证据保留（seed200 pilot）。FD-proxy 训练**降级为 ablation**，不是最终可微层。

### Phase A PASS
Containment + forest MIQP regressions；`engineering_baseline_103faa1.json`。

### Phase B PASS
`docs/diff-time-qp-mapping.md`。

### Phase C PASS（方法选定）
- True Diff-QP：`prototypes/time_fixed_z_qp/diff_time_qp_kkt.py`（active-set KKT）  
- CvxpyLayer 全矩阵 Parameter 路径否证：`evidence/diff_time_qp_probe0.json`

### Phase D PASS（梯度验证）
- pack16：15/16 同时通过 jerk + solution FD oracle（失败保留）  
- `evidence/phase_d_grad_validation_pack16.json`

### Phase E PASS
- Loss：`L = J/J_scale + λ T/T_scale`；scales 仅来自 train pack  
- λ search seed0：`{0, 0.1, 0.3, 1.0}` → 选定 **λ=0.1** 作为 jerk+time  
- Fair arms：supervised / FD-proxy / true-diff KKT（jerk-only + jerk+time），3 seeds  
- Offline oneshot + verdict under `prototypes/time_fixed_z_qp/evidence/phase_e_train/`  
- Primary model：`timing_kkt_lam0.1_seed0.json`

### Phase G probe PASS（seed200）
- Script：`scripts/run_phase_g_oneshot.sh`  
- Run：`docker/dev-workspace/results/request-latency-v3/online/phase_g_probe_seed200_c`  
- Evidence：`docs/request-latency-v2/evidence/analysis/phase_g_oneshot_probe_seed200.json`  
- goal_reached；956 oneshot appends with `fallback=false`；956 `controller_first_use` events  
- Frozen Z=`corridor-cost.json`；real C(T)；instrumented binary required under `install-dev/sando/lib/sando/`

### Phase J partial → improved by Phase G probe
- Identity chain live-verified on seed200 (publish + controller_first_use)  
- Still missing：observation/corridor content hashes on every event（optional fill during Phase K）

---

## Active Hypothesis

True Diff-QP timing (λ=0.1) + frozen Z one-shot is online-viable on seed200; multi-seed 200–205 will show whether latency/task trade-offs beat supervised and Original.

---

## Current Bottleneck

Phase F 100-step trains still running; then fair multi-seed pilots (Phase K).

---

## Next Automatic Action

1. Finish Phase F 100×3seed KKT λ∈{0,0.1} → offline oneshot compare vs Phase E  
2. Phase K：seeds 200–205 fair compare Original / supervised / FD / true-diff  
3. Apply Phase L decision rules; write `docs/final-study/` when §3 met  

---

## Blocked Only If External

无外部阻塞。
