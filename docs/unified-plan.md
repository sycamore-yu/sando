# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
近期 HEAD：`b0d6d19`  
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
| 7 | 在线 baseline 不可行关闭 | **进行中**：走廊/indicator 为冻结观测不可行主因；install-dev 重建中准备 seed200 冒烟 |
| 8 | ≥10 条 one-shot 控制端使用 | 未开始（依赖 7） |
| 9 | supervised vs differentiable 对照 | **部分离线**（oneshot_offline_*）；缺在线 |
| 10 | 原 SANDO vs single-shot 正式比较 | 未开始 |
| 11 | 完整请求延迟与任务表现最终表 | 未开始 |
| 12 | 身份齐全 | 进行中 |

---

## 关键产物

| 项 | 路径 |
| --- | --- |
| 耗时归因 | `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md` |
| 时间可微原型 | `prototypes/time_fixed_z_qp/` |
| QP 训练模型 seed0–2 | `prototypes/time_fixed_z_qp/evidence/train16_run/timing_qp_seed*.json` |
| T→C(T) | `prototypes/time_fixed_z_qp/evidence/t_to_c_scan/t_to_c_conclusion.json` |
| 离线 one-shot | `prototypes/time_fixed_z_qp/evidence/oneshot_offline_*.json` |
| 不可行分组 | `docs/request-latency-v2/evidence/analysis/infeasibility_group_diagnosis.json` |

---

## 执行队列（当前）

```
✅ 0–6 离线机制主链（归因→可微→训练→T→C→one-shot 部分）
→ 7 在线不可行：走廊冲突根因 → 最小修复（不放宽安全约束）
→ 8–11 控制端 one-shot≥10；三组正式比较；最终表
```

**当前活动项：7（在线走廊不可行最小修复 + seed200 冒烟）。**

---

## 冻结耗时背景（禁止混写）

selected60 k=1 cost 更快；阶段2 在线 total_ms cost 更慢；3.87× 仅 persistent 生命周期。
