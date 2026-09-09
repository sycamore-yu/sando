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

**Phase F — Expand timing training (100 updates, 3 seeds) then Phase G one-shot deploy**

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
- Fair arms：supervised / FD-proxy / true-diff KKT（jerk-only + jerk+time），3 seeds（FD λ0.1 seed0）  
- Offline oneshot：`prototypes/time_fixed_z_qp/evidence/phase_e_train/offline_oneshot_compare.json`  
- Verdict：`.../phase_e_verdict.json`  
- Primary model：`timing_kkt_lam0.1_seed0.json`（vs supervised：jerk↓、accept 15→14/16、T↑）

### Phase J partial（compile）
- `notePublishComplete` + `noteControllerFirstUse` identity chain  
- Evidence：`docs/request-latency-v2/evidence/analysis/phase_j_controller_first_use.json`  
- Still missing：observation/corridor hashes on every event + live JSONL sample（fill in Phase K）

---

## Active Hypothesis

True Diff-QP timing with λ=0.1 trades a small accept-rate drop for much lower accepted jerk; online one-shot with frozen Z and real C(T) will show whether latency/task metrics justify the trade-off vs supervised.

---

## Current Bottleneck

Need Phase F 100-step models + Phase G online one-shot harness with frozen `corridor-cost.json` Z and real C(T).

---

## Next Automatic Action

1. Phase F：100 updates × 3 seeds for kkt λ=0 and λ=0.1（failures retained）  
2. Phase G：deploy selected timing model + frozen Z → 1T+1Z+1QP offline/online probe  
3. Complete Phase J hashes when capture path is on during pilots  
4. Phase K：seeds 200–205 fair A–E compare  

---

## Blocked Only If External

无外部阻塞。
