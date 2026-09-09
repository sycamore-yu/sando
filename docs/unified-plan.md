# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi`  
远端：`personal/feat/ampl-gurobi`  
执行：唯一实施负责人，顺序推进；禁止其它 agent 同树写入/构建。

权威关闭定义见《SANDO 单代理自主完成总任务》（`docs/fromchat/` 草稿保留）。本文件只维护**当前真实状态与队列**。

---

## 当前 HEAD / 现场

| 项 | 值 |
| --- | --- |
| 推送基线（本轮前） | `f307b37` |
| 只读成果树 | `sando-time-policy` @ `4ab4131` |
| 可微 z-原型只读 | `/home/tong/tongworkspace/refer/L2O-sando/prototypes/fixed_z_qp` |
| 时间可微工作区 | `prototypes/time_fixed_z_qp/` |
| Python 环境 | conda `genesis`（cvxpy/cvxpylayers/torch） |
| Gurobi/AMPL | `sando-dev` + `docker/dev_env.sh` |

---

## 关闭清单

| # | 门槛 | 状态 |
| ---: | --- | --- |
| 1 | Z 路线分层耗时结论冻结 | **通过** |
| 2 | fixed-C/fixed-Z 时间可微 QP 前向一致 | **通过**（Python↔Gurobi rel≤4e-6；不可行因子双方一致） |
| 3 | 时间梯度有限差分通过或明确失败结论 | **通过**（dJ/df 三尺度稳定，rel~1e-6） |
| 4 | 时间网络经 QP trajectory gradient 更新 | **部分**：标量 f 经 QP 轨迹梯度更新已通过；真实 time NN 权重更新待做 |
| 5 | 真实 T→C(T) 重建 | 未开始 |
| 6 | 单 T + 单 Z + 单 QP 离线链 | 基础设施有；正式验收未做 |
| 7 | 在线 baseline 不可行关闭 | 阻塞中（不挡离线可微） |
| 8 | ≥10 条 one-shot 轨迹被控制端使用 | 未开始 |
| 9 | supervised vs differentiable 对照 | 未开始 |
| 10 | 原 SANDO vs single-shot 正式比较 | 未开始 |
| 11 | 完整请求延迟与任务表现最终表 | 未开始 |
| 12 | 模型/commit/配置/结果/复现身份齐全 | 进行中 |

---

## 已冻结耗时背景（禁止混写）

1. selected60/k=1：cost 单时间链更快（52.4 vs 73.9 ms）；adapter+Runtime；首提议 0.700 + 回退 0.050。
2. 阶段2 在线请求 `total_ms`：cost 更慢（并行+多候选+drain）。
3. fresh→persistent ≈3.87× 仅生命周期。

---

## 执行队列（当前）

```
✅ 0 接管 WIP → commit → push
✅ 1 fixed-C/fixed-Z 前向 vs Gurobi + FD dJ/df
→ 2 真实 time NN（既有 timing policy）经 QP 轨迹梯度小批更新（16×100）
→ 3 3 seeds + val；再 T→C(T)
→ 4 冻结 cost Z 接入 one-shot 离线链
→ 5 在线 baseline 约束组诊断
→ 6 ≥10 条控制端 one-shot；三组正式比较
```

**当前活动项：2（time NN through QP）。**

---

## 阶段记录

### 2026-09-09 — 耗时归因关闭
- `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md`

### 2026-09-09 — fixed-C/fixed-Z 时间前向 + FD + 标量训练烟测
- C++：`tests/ampls/time_fixed_z_forward_probe.cpp`（live rebuild，固定走廊+Z）
- Python：`prototypes/time_fixed_z_qp/`
- 证据：`data/gurobi_forward_report.jsonl`, `forward_compare.json`, `python_fd_report.json`, `train_smoke_report.json`
- 原生 f≈2.3：Gurobi obj 91659.8127 ≈ Python jerk 91659.601（rel 2.3e-6）；残差 valid；与 freezeAssignment 一致
- 标量 f：full_qp 从 2.0→~2.31，jerk 212k→95k；frozen/stop 不变；λ_T=0
