# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi`  
远端：`personal/feat/ampl-gurobi`  
执行：唯一实施负责人，顺序推进；禁止其它 agent 同树写入/构建。

权威关闭定义与工作规则见用户指令《SANDO 单代理自主完成总任务》（`docs/fromchat/` 草稿保留，不覆盖）。本文件只维护**当前真实状态与队列**。

---

## 当前 HEAD / 现场

| 项 | 值 |
| --- | --- |
| 本地 HEAD（接管时） | `b04506a` |
| personal 远端（接管时） | `095cfb5`（本地曾 ahead） |
| 只读成果树 | `sando-time-policy` @ `4ab4131` |
| 可微原型只读来源 | `/home/tong/tongworkspace/refer/L2O-sando/prototypes/fixed_z_qp`（z 参数；无时间 f） |
| Docker | `sando-dev` 等已在跑；构建时源码静止 |

---

## 关闭清单（全部完成才结束）

| # | 门槛 | 状态 |
| ---: | --- | --- |
| 1 | Z 路线分层耗时结论冻结 | **通过** → `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md` |
| 2 | fixed-C/fixed-Z 时间可微 QP 前向一致 | 进行中 |
| 3 | 时间梯度有限差分通过或明确失败结论 | 未开始 |
| 4 | 时间网络经 QP trajectory gradient 更新 | 未开始 |
| 5 | 真实 T→C(T) 重建 | 未开始 |
| 6 | 单 T + 单 Z + 单 QP 离线链 | 部分基础设施已有；正式验收未做 |
| 7 | 在线 baseline 不可行关闭 | 阻塞中（不挡离线可微） |
| 8 | ≥10 条 one-shot 轨迹被控制端使用 | 未开始 |
| 9 | supervised vs differentiable 对照 | 未开始 |
| 10 | 原 SANDO vs single-shot 正式比较 | 未开始 |
| 11 | 完整请求延迟与任务表现最终表 | 未开始 |
| 12 | 模型/commit/配置/结果/复现身份齐全 | 进行中 |

---

## 已冻结耗时背景（禁止混写）

1. **selected60 / k=1 / 同 T·走廊：** cost `timing.total_ms` 中位 52.4 vs original 73.9（更快）；节省来自 adapter + Gurobi Runtime；ranking≈2.5 ms。最终接受 0.750；cost 首提议 0.700 + 回退 0.050。
2. **阶段2 在线请求 `total_ms`：** cost 更慢；主因多时间并行 + 多 Z 候选 + cancel/drain，不是选中分支 QP 更慢。
3. **fresh→persistent ≈3.87×：** 仅生命周期，不是方法加速比。

剩余耗时工程项：`k=1 在线 规划输入→可用轨迹`（最终验收，不阻塞可微训练）。

---

## 执行队列（当前）

```
0 接管 WIP → 小 commit → push personal
1 fixed-C/fixed-Z：时间参数化前向 vs 当前 Gurobi（真实 PlanningInstance）
2 时间梯度：u*/B*/训练损失 的 FD；stop-grad 对照
3 16 例 ×100 step 时间网络经 QP 更新；再 3 seed
4 真实 T→C(T)；再接冻结 cost Z；one-shot 离线链
5 在线 baseline 约束组诊断最小修复
6 ≥10 条控制端使用的 one-shot；三组正式比较与最终表
```

**当前活动项：0→1**（可微时间前向）。

---

## 阶段记录

### 2026-09-09 — 耗时归因关闭

- 交付归因结论 md/json；统一计划建立。
- 下一：清理 stage metrics / null_class 诊断 commit 后进入可微 QP。

### WIP 去向（待本轮 commit）

- replan stage flags（`sando.hpp`/`sando.cpp`）：长期诊断 → commit。
- `null_class_decomp_probe`：空分类回归 → commit。
- fromchat 用户草稿：保留未跟踪，不覆盖。
- `.agents/` / `.codex/`：不入生产树。
