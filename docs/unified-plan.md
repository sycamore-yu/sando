# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
执行：唯一实施负责人，顺序推进。

---

## 关闭清单

| # | 门槛 | 状态 |
| ---: | --- | --- |
| 1 | Z 路线分层耗时结论冻结 | **通过** |
| 2 | fixed-C/fixed-Z 时间可微 QP 前向一致 | **通过** |
| 3 | 时间梯度有限差分通过 | **通过** |
| 4 | 时间网络经 QP trajectory gradient 更新 | **通过**（3 seeds，16×100） |
| 5 | 真实 T→C(T) 重建 | **通过（有范围）** |
| 6 | 单 T+单 Z+单 QP 离线链 | **部分**（14–15/16） |
| 7 | 在线 baseline 不可行关闭 | **修复已落地，待在线冒烟确认**：根因=HGP 体素中心路径端点导致 start 落在走廊外；endpoint snap 后冻结森林观测 MIQP optimal |
| 8 | ≥10 条 one-shot 控制端使用 | 未开始（依赖 7 在线确认） |
| 9 | supervised vs differentiable 对照 | **部分离线**；缺在线 |
| 10 | 原 SANDO vs single-shot 正式比较 | 未开始 |
| 11 | 完整请求延迟与任务表现最终表 | 未开始 |
| 12 | 身份齐全 | 进行中 |

---

## 门槛 7 证据

| 项 | 路径 |
| --- | --- |
| 修复前 containment | `docs/request-latency-v2/evidence/analysis/corridor_containment_forest2_f2.json` |
| 修复后 containment | `docs/request-latency-v2/evidence/analysis/corridor_containment_forest2_f2_after_snap.json` |
| 根因说明 | `docs/request-latency-v2/evidence/analysis/corridor_start_outside_root_cause.json` |
| 修复后 ablation | `docs/request-latency-v2/evidence/analysis/infeasibility_group_after_snap.json` |
| seed200 修复前冒烟失败 | `docs/request-latency-v2/evidence/analysis/online_smoke_seed200_pre_snap_failure.json` |

代码：`planLocalTrajectory` 与 `reconstruct_planning_request::prepare` 将 path 端点 snap 到连续 start/goal。

---

## 执行队列（当前）

```
✅ 0–6 离线机制主链
→ 7 在线冒烟确认 endpoint snap（seed200 original）
→ 8–11 控制端 one-shot≥10；三组正式比较；最终表
```

**当前活动项：7 在线确认。**

---

## 冻结耗时背景（禁止混写）

selected60 k=1 cost 更快；阶段2 在线 total_ms cost 更慢；3.87× 仅 persistent 生命周期。
