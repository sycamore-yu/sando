# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi`  
远端：`personal/feat/ampl-gurobi`  
HEAD（近期）：`f9fee5d`  
执行：唯一实施负责人，顺序推进；禁止其它 agent 同树写入/构建。

权威关闭定义见《SANDO 单代理自主完成总任务》（`docs/fromchat/` 草稿保留）。本文件只维护**当前真实状态与队列**。

---

## 关闭清单

| # | 门槛 | 状态 |
| ---: | --- | --- |
| 1 | Z 路线分层耗时结论冻结 | **通过** |
| 2 | fixed-C/fixed-Z 时间可微 QP 前向一致 | **通过**（Python↔Gurobi rel≤4e-6） |
| 3 | 时间梯度有限差分通过或明确失败结论 | **通过**（dJ/df 三尺度稳定） |
| 4 | 时间网络经 QP trajectory gradient 更新 | **通过（机制）**：16×100 MLP；seed0 0.279→0.190；seed1 0.340→0.190；seed2 运行中 |
| 5 | 真实 T→C(T) 重建 | **通过（有范围）**：空图全 f 最优；forest obs 走廊重建 plane_count 稳定但 MIQP 全不可行 |
| 6 | 单 T + 单 Z + 单 QP 离线链 | 未正式验收 |
| 7 | 在线 baseline 不可行关闭 | 阻塞（全 MIQP status=3；不挡离线） |
| 8 | ≥10 条 one-shot 轨迹被控制端使用 | 未开始 |
| 9 | supervised vs differentiable 对照 | 未开始 |
| 10 | 原 SANDO vs single-shot 正式比较 | 未开始 |
| 11 | 完整请求延迟与任务表现最终表 | 未开始 |
| 12 | 模型/commit/配置/结果/复现身份齐全 | 进行中 |

---

## 已冻结耗时背景（禁止混写）

1. selected60/k=1：cost 单时间链更快（52.4 vs 73.9 ms）。
2. 阶段2 在线请求 `total_ms`：cost 更慢（并行+多候选+drain）。
3. fresh→persistent ≈3.87× 仅生命周期。

---

## 执行队列（当前）

```
✅ 0–1 接管、归因、fixed-C/Z 前向+FD
✅ 2 timing MLP via QP grads（seeds 收尾）
→ 3 T→C(T) 重建扫描与局部梯度范围声明
→ 4 冻结 cost Z + one-shot 离线链
→ 5 在线 baseline 约束组诊断（最小修复）
→ 6 ≥10 控制端 one-shot；三组正式比较；最终表
```

**当前活动项：4（one-shot 离线链）+ 5（在线约束组诊断）。**

---

## 阶段记录

### 2026-09-09 — 耗时归因关闭
- `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md`

### 2026-09-09 — fixed-C/fixed-Z 前向 + FD + 标量烟测
- `tests/ampls/time_fixed_z_forward_probe.cpp`
- `prototypes/time_fixed_z_qp/`

### 2026-09-09 — timing MLP QP trajectory training
- Pack：`prototypes/time_fixed_z_qp/evidence/train16_pack_geometry.json`
- Init：`joint-time-v2/models/timing-schema2-regression.json`
- Seed0 model sha256 `11f273ad2bac040fbf8db9cb4d673506aca3c98a7364c5f05ef5887242980f19`
- 14/16 样本有有效 QP 梯度；2 样本前向不可行保留分母
