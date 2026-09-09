# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
近期 HEAD：见 `git rev-parse HEAD`  
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
| 7 | 在线 baseline 不可行关闭 | **通过**（endpoint snap；seed200 original goal_reached） |
| 8 | ≥10 条 one-shot 控制端使用 | **通过**（seed200：1195 次 one-shot QP append；goal_reached；fallback 5 计入分母） |
| 9 | supervised vs differentiable 对照 | **进行中**（离线已有；在线 supervised 冒烟运行中） |
| 10 | 原 SANDO vs single-shot 正式比较 | **部分**（同 seed200：original vs oneshot 延迟/任务表已出） |
| 11 | 完整请求延迟与任务表现最终表 | **部分**（`comparison_table_partial.json`） |
| 12 | 身份齐全 | 进行中 |

---

## 关键证据

| 项 | 路径 |
| --- | --- |
| 耗时归因 | `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md` |
| 时间可微原型 | `prototypes/time_fixed_z_qp/` |
| 走廊 start-outside 根因 | `docs/request-latency-v2/evidence/analysis/corridor_start_outside_root_cause.json` |
| Gate7 在线确认 | `docs/request-latency-v2/evidence/analysis/online_smoke_seed200_post_snap.json` |
| Gate8 one-shot | `docs/request-latency-v2/evidence/analysis/oneshot_gate8_seed200.json` |
| 比较表（部分） | `docs/request-latency-v2/evidence/analysis/comparison_table_partial.json` |

---

## 执行队列（当前）

```
✅ 1–8（含在线不可行关闭与 ≥10 one-shot）
→ 9 完成在线 supervised vs QP-timing 对照
→ 10–12 固化正式比较表与身份清单
```

**当前活动项：9（supervised 在线配对）。**

---

## 冻结耗时背景（禁止混写）

selected60 k=1 cost 更快；阶段2 在线 total_ms cost 更慢；3.87× 仅 persistent 生命周期。

同 seed200 冒烟：oneshot（QP-timing+cost）total_ms p50≈25ms；original 多因子 p50≈41ms；两者均 goal_reached。
