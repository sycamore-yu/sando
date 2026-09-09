# SANDO unified plan（唯一总计划）

日期：2026-09-09  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
执行：唯一实施负责人。

---

## 关闭清单

| # | 门槛 | 状态 |
| ---: | --- | --- |
| 1 | Z 路线分层耗时结论冻结 | **通过** |
| 2 | fixed-C/fixed-Z 时间可微 QP 前向一致 | **通过** |
| 3 | 时间梯度有限差分通过 | **通过** |
| 4 | 时间网络经 QP trajectory gradient 更新 | **通过** |
| 5 | 真实 T→C(T) 重建 | **通过（有范围）**：空图全可行；森林重建成功但修复前 MIQP 不可行 |
| 6 | 单 T+单 Z+单 QP 离线链 | **部分通过**：QP-timing 14/16、supervised 15/16；失败保留在分母 |
| 7 | 在线 baseline 不可行关闭 | **通过**（endpoint snap） |
| 8 | ≥10 条 one-shot 控制端使用 | **通过**（1195 one-shot QP append，seed200） |
| 9 | supervised vs differentiable 对照 | **通过**（离线+在线 seed200 配对） |
| 10 | 原 SANDO vs single-shot 正式比较 | **通过**（同 seed200 正式表） |
| 11 | 完整请求延迟与任务表现最终表 | **通过**（seed200 三方法表；更大种子集可扩展） |
| 12 | 身份齐全 | **通过**（`IDENTITY.md` + final table） |

---

## 最终表与身份

- `docs/request-latency-v2/evidence/analysis/final_latency_task_table_seed200.json`
- `docs/request-latency-v2/evidence/analysis/IDENTITY.md`

---

## 研究结论（证据支持）

1. 在线“走廊 OK 但全 MIQP status=3”主因是 HGP 体素中心路径端点与连续 start 错位，不是动力学过硬。
2. Endpoint snap 恢复可行性与运动，无需放宽安全约束。
3. 时间网络可用轨迹代价 FD 梯度更新；fixed-C 下时间梯度稳定。
4. 同 seed200：one-shot（单 T+单 Z+QP）请求 `total_ms` p50 低于原多因子 SANDO，两者均到达目标。
5. Supervised 与 QP-timing 在线表现接近；离线 accept 率 supervised 略高（15/16 vs 14/16）。

---

## 证据支持的下一步（仅此）

- 将 endpoint snap 回归测固化到 CI（containment probe + seed200 smoke）。
- 在更多 test-split 种子上扩展 final table（200–229），不要改约束换通过率。
- 离线 2/16 与 1/16 失败样本做单独几何归因（已在分母中）。
