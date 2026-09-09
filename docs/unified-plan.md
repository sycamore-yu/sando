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

**Phase E — Task-aligned timing objective（jerk + λT）+ fair supervised/FD/true-diff training**

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
- `evidence/diff_time_qp_kkt_probe0.json`

---

## Active Hypothesis

True Diff-QP（KKT）+ λT time term 相对 supervised / FD-proxy 给出更干净梯度，并在 validation 上不劣于 supervised。

---

## Current Bottleneck

尚未完成 λ 搜索与三路公平训练；未进入 200–205 pilot / controller-first-use。

---

## Next Automatic Action

1. 实现 `L = J/J_scale + λ T/T_scale`（scale 仅来自 train）。  
2. 三路：supervised / FD-proxy / true-diff（jerk-only 与 jerk+time）。  
3. 3 seeds small validation → 选模型进 one-shot（仍用 corridor-cost Z）。

---

## Blocked Only If External

无外部阻塞。
