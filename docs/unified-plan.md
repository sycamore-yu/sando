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

Stop and report “All done” **only** when `docs/fromchat/plan.md` §3 Ultimate Definition of Done is fully evidenced.

---

## Current Milestone

**Phase C — True differentiable time-QP**（Phase A/B PASS）

---

## Completed Evidence（Milestone 0 / Phase I engineering baseline）

旧 Gate 1–12 保留为已完成工程基线（不是 Ultimate Done）：

| 旧 Gate | 结论 | 证据 |
| ---: | --- | --- |
| 1 | Z 耗时归因冻结 | `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md` |
| 2–4 | fixed-C/Z 前向 + FD + FD-proxy NN 更新 | `prototypes/time_fixed_z_qp/` |
| 5 | T→C(T) 重建（有范围） | `prototypes/time_fixed_z_qp/evidence/t_to_c_scan/` |
| 6 | 离线 one-shot 部分 | oneshot_offline_*（失败在分母） |
| 7 | endpoint snap 关闭在线全不可行 | corridor_* / online_smoke_seed200_* |
| 8–12 | seed200 pilot 表与身份 | `final_latency_task_table_seed200.json`, `IDENTITY.md` |

**明确降级：** 当前 timing 训练是 **FD trajectory-sensitivity prototype**，不算 true differentiable optimizer training（plan §4.5 / §3.1）。

---

## Active Hypothesis

True Diff-QP（CVXPYLayers DPP 或 KKT implicit diff）相对 supervised / FD-proxy，能提供更干净、可复现的 timing 梯度，并在多 seed 上改善或持平 task/latency trade-off。

---

## Current Bottleneck

1. FD 被误当作最终可微层 → 需 Phase B 映射 + Phase C 真可微实现。  
2. 泛化仍停在 seed200 pilot。  
3. `publish_seen` / controller-first-use 事件链不完整（plan §3.5 / Phase J）。

---

## Next Automatic Action

1. 固化 endpoint containment regression（断言 start/goal 在走廊内）。  
2. 最小 planning regression：snap 后冻结森林观测须 MIQP optimal。  
3. 冻结 baseline identity（103faa1 + models + solver/benchmark）。  
4. PASS → Phase B：`docs/diff-time-qp-mapping.md`。

---

## Blocked Only If External

仅 plan §7 所列硬阻塞可停；当前无外部阻塞。
