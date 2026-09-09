# Z分配路线耗时归因结论

日期：2026-09-09  
负责人：本活动分支唯一实施会话  
活动分支：`feat/ampl-gurobi`  
本地接管身份：`b04506a`（相对 `personal/feat/ampl-gurobi` ahead 1）  
总计划：`docs/unified-plan.md`（由当日总任务书同步）

**假设：** 读者熟悉 SANDO 重规划、离线 `replay_integer_planning`、以及“代价监督 = cost 模型提出完整 Z”这一分工；不要求已读全部阶段报告原文。

---

## 0. 一句话结论（按层级分开）

在【离线 selected60 / git 证据基线 `3a13bf9` / 冻结 T+走廊 / `candidate_limit=1` / 每方法一次新建 runtime】下，**代价监督相对原 MIQP，在「单时间决策与求解链」更快**：全部 300 次输入的 `timing.total_ms` 中位数 **52.4 vs 73.9 ms**（约 −29%），p95 **72.0 vs 130.7 ms**；配对双方首提议均接受的 210 次上，中位差约 **−25.7 ms**。主要有证据因素是 **适配层（adapter）与求解器内部（Gurobi Runtime）同时更短**；网络排序约 **2.5 ms**，不是主导。原约束残差检查在接受样本上通过；最终接受率同为 **0.750**，但代价监督首提议接受 **0.700**，另有 **0.050** 靠 MIQP 回退。

在【阶段2在线完整飞行 / 发布镜像 `sando-learning-release:595ab0d8c31f9a48ebba` / 历史多时间候选 + `integer_proposals_per_factor=3`】下，**代价监督相对原方法，在「规划输入→指标写出（旧 `total_ms`）」更慢**：动态/森林 p95 **1066.0 / 811.0 vs 708.7 / 409.6 ms**。主要有证据因素是 **多因子并行区段与取消等待拉长请求临界路径**，而不是“选中分支的单时间策略本身更慢”（选中分支 `policy.total_ms` 中位数代价监督往往更低）。

**规划输入→可用轨迹（追加成功边界）** 与 **k=1 在线配对** 本轮仍受在线运动/不可行阻塞，标为**待验收**；不以离线加速外推在线。

---

## 1. 旧“学习更慢”数字：字段、起止点、版本

| 项 | 内容 |
| --- | --- |
| 报告数字 | 原方法动态/森林 p95 **708.7 / 409.6 ms**；代价监督 **1066.0 / 811.0 ms**（`docs/learning-stages-0-5.md` 阶段2） |
| 计时字段 | 请求级 **`total_ms`** |
| 源码起点 | `SANDO::replan` 入口 `steady_clock`（`src/sando/sando.cpp`，约 703 行起） |
| 源码终点 | 同函数内写出 `replan_metrics.jsonl` 前（含全局路径、局部并行规划、取消等待、回收、追加尝试） |
| 取值链 | `replan_metrics.jsonl.total_ms` → `scripts/run_integer_learning_evaluation.py` 的 `episode_record.planning_latency_ms`（观察窗 + `planning_attempted`）→ `scripts/report_integer_learning_evaluation.py` 百分位 |
| 明确排除 | 轨迹话题 `publish_ms`、相机渲染、异步建图、控制端首次消费 |
| 运行条件 | 历史时间搜索策略；每因子最多 3 个整数候选；闭环飞行状态，非冻结同一观察 |
| 结果筛选 | 成功与失败请求均可进入旧统计；曾出现启动缺陷导致亚毫秒假失败，最终表为修正后版本 |

**核验结论：** 旧“更慢”是 **在线请求级墙钟**，不是单时间固定问题，也不是 Gurobi Runtime。

---

## 2. 计时词典与分层实测（本轮复算）

### 2.1 字段映射（已核对）

| 层级（总任务书） | 现用字段 | 边界摘要 | 本轮状态 |
| --- | --- | --- | --- |
| 规划输入→可用轨迹 | 成功路径接近 `total_ms`（含追加）；`usable_ms` 为求解结果就绪、追加前 | 失败应空置“可用轨迹耗时”；旧链仍用 `total_ms` | 在线 k=1 正式对照 **阻塞**；阶段2 记录中 `usable_ms` 基本为 0（当时未填） |
| 局部规划全链 | 无单一字段；`parallel_ms` ≈ 多时间任务墙钟（不含静态预分解与时间推理） | 与 `cancel_drain_ms` 分开 | 阶段2 有数；selected12 全量 `replan_metrics` **缺失** |
| 单时间决策求解链 | 在线 `policy.total_ms`；离线 replay `timing.total_ms` | 输入已含 T 与走廊 | **selected60 已充分** |
| 求解器内部 | `backend_ms` / `gurobi_computation_time` ← Gurobi `Runtime` | 不含 AMPL 导出/编译/导入 | **selected60 + 阶段2 选中分支均有** |
| 网络/排序 | `ranking_ms`；时间头为 `timing_policy.inference_ms` | 特征若在 `rank` 外则未单列 | 离线约 2.5 ms |
| 建模适配 | 离线 `adapter_ms`；在线多藏在 `callOptimizer`/TRACE | 与 Runtime 必须分列 | 离线主导项 |
| 回退 | `fallback_ms` / `fallback_used` | 独立身份 | 离线 cost 15/300 回退后接受 |
| 调度等待 | `cancel_drain_ms` | 非 `usable_ms` 子集 | 阶段2 尾部可见 |
| 运行时生命周期 | fresh vs persistent 进程墙钟与 TRACE | **不是**方法间加速比 | 约 **3.87×** 进程加速，接受 120/120 一致 |

### 2.2 同状态、同时间、同走廊配对（试验一 / selected60）

**条件：** 60 独立请求 × 5 正式重复 = 300/方法；`candidate_limit=1`；`runtime_reuse=one_fresh_runtime_per_method`；模型为阶段2选定 bc/cost 路径；证据摘要见 `selected60_first_vs_fallback.md`（本机复算一致）。

| 方法 | 首提议接受 | 回退后接受 | 最终接受 | 最终失败 | `total_ms` 中位/p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| original | 225 | 0 | 225 | 75 | 73.9 / 130.7 |
| cost | 210 | 15 | 225 | 75 | 52.4 / 72.0 |
| bc | 200 | 25 | 225 | 75 | 53.3 / 76.8 |

**分层（全部 300 次，ms）：**

| 区段 | original 中位/p95 | cost 中位/p95 | 说明 |
| --- | ---: | ---: | --- |
| `timing.total_ms` | 73.9 / 130.7 | 52.4 / 72.0 | 单时间决策求解链 |
| `adapter_ms` | 66.7 / 96.5 | 45.8 / 57.0 | 建模适配占墙钟约 **87–89%** |
| `backend_ms`（Runtime） | 8.2 / 31.4 | 2.7 / 9.9 | 固定 QP ≪ MIQP 内部 |
| `ranking_ms` | 0 / 0 | 2.5 / 2.7 | 网络侧很小 |
| `model_prepare_ms` | 0 / 0 | 1.1 / 1.5 | 固定赋值准备 |
| `fallback_ms` | 0 / 0 | 0 / 8.3（均值 2.4） | 仅失败路径累加 |

**配对双方均为首提议接受（n=210）：** cost−original 的 `total_ms` 中位 **−25.7 ms**（p95 差仍为负）。其中 adapter 中位差约 **−21.7 ms**，backend 约 **−7.0 ms**；ranking 约 **+2.5 ms**，远小于前两项节省。

**目标质量（双方均接受，n=225）：** 目标差中位 **0**；约 140/225 数值同号级一致，60 次 cost 更高、25 次更低；相对差中位 0、p95 约 0.13。残差结构在接受样本上 `valid=True`（原检查门槛）。

### 2.3 新建 vs 持久复用（生命周期，非方法差）

selected12、k=1、两正式种子：整批进程墙钟约 **3.87×**（fresh→persistent）；接受/目标/残差一致。  
**解释范围：** 该离线试验的 AMPL import/compile 开销。  
**不得**写成“学习方法相对原方法加速 3.87 倍”。

### 2.4 在线请求级与局部并行（阶段2 原始 metrics 复算）

| 指标 | original | cost |
| --- | ---: | ---: |
| 请求 `total_ms` p50/p95（全场景混合） | 16.9 / 540 | 32.7 / 897 |
| `parallel_ms` p95 | 515 | 871 |
| `cancel_drain_ms` p95 | 133 | 175 |
| 有取消等待的请求比例 | 26% | 37% |
| `total_ms>500` 比例 | 6.3% | 14.2% |
| 选中分支 `policy.total_ms` p50/p95 | 190 / 352 | **114 / 301** |
| 选中分支 `ranking_ms` p50 | 0 | 4.8 |
| 尝试 `backend_ms` p50 | 35.9 | **5.9** |

**归因要点：** 在线 p95 变差主要落在 **并行因子墙钟 + 取消等待 + 慢请求变多**；选中分支的单时间策略与求解器内部并不支持“固定分配 QP 本身更慢”。这与离线 selected60“单时间更快”一致，也解释了两组旧证据为何可同时成立。

### 2.5 规划输入→可用轨迹 / 在线 k=1

| 项 | 状态 |
| --- | --- |
| 协议 | `online_timing_dev4.json`（original vs cost，k=1） |
| 阻塞 | 冒烟与 A/B：无有效追加、`usable_ms=0`；诊断见 `online_ab_motion_diagnosis.json`（如全 MIQP status=3） |
| selected12 与阶段2 | 种子不重叠；capture 常为 `metrics:null`，无法把同一 request_id 的 online `total_ms` 与 offline 对齐 |

本层正式快慢结论：**未关闭**；不阻塞离线单时间归因结论。

---

## 3. 主要原因（有证据 / 对照）

| 现象 | 区段 | 对照 | 单因素含义 |
| --- | --- | --- | --- |
| 离线单时间 cost 更快 | adapter + backend | selected60 同 T/走廊/k=1 | 固定 Z 的 QP 适配与 Runtime 均短于原 MIQP；排序开销可忽略 |
| 离线最终接受率相同但首提议更低 | fallback | first vs fallback 分类 | 最终 75% 含 5% MIQP 回退；不可把 blended accept 写成首提议成功 |
| 离线墙钟仍以适配为主 | adapter share ~88% | TRACE / fresh-pers | 方法差之外，生命周期决定该试验绝对耗时量级 |
| 在线旧 p95 更大 | parallel + cancel_drain + 多候选 | 阶段2 metrics vs 离线 k=1 | 历史预算（多时间×最多3候选）与并行取消，不是“网络推理慢” |
| 在线选中分支策略往往更快 | policy.total / backend | 阶段2 选中因子 | 与离线同向；不能用请求 `total_ms` 反推单次 QP 变慢 |

**未归因残差：** 在线慢请求中，失败分支在取消前的模型导入/锁竞争尚未逐请求拆完；规划输入→控制消费无时间戳。

---

## 4. 已修问题、剩余代价、时效预算、下一接口

### 已修 / 已冻结（服务归因与复现）

- 请求指标与复用/重建挂钩（`095cfb5` 等）；本机 `b04506a` 起冻结图分类仅在 capture。
- `--candidate-limit 1` 与 selected60/12 正式重放。
- `--runtime-reuse persistent` 与 TRACE 对照（生命周期修复，接受不变）。
- 首提议 vs 回退分类报告，避免 75% 误读。

### 剩余代价（仍成立）

- 离线：即使 cost 更快，**adapter 仍占绝大部分**；要再压 τ，需针对适配/持久化，而不是再砍 ranking。
- 在线历史配置：多因子并行与取消等待仍可主导请求 p95。
- 学习路径：**回退率非零**（cost 离线 5% 回退后成功）；一次性主求解目标要求回退调用为零，属后续阶段。

### 实际时效含义

- **可宣称（离线单时间链）：** 冻结模型 + 同 T/走廊 + k=1 + 新建 runtime 下，代价监督获得接受轨迹的决策求解链 **更快**，成功率与原方法最终接受对齐，首提议略低。
- **不可宣称：** 当前部署在线“规划输入→可用轨迹”已更快；阶段2 证据仍是更慢。
- **预算提醒：** 旧在线 p95 已到 ~0.7–1.1 s 量级；离线单时间中位 ~50–80 ms 不得直接当作机载重规划预算。

### 下一阶段接口（总队列 4 起）

耗时归因阶段在**离线主问题**上关闭；在线 k=1 恢复仍属本阶段残余测量，但不再阻塞启动：

1. 真实轨迹代价 → 可微硬约束 QP → 回传时间/联合网络（总任务书 §9）。
2. 运行保持：单时间、单完整 Z、一次主 QP、原约束+时效+追加+控制端使用、回退分列统计。

---

## 5. 规定格式首段（可摘录）

在【本地 `b04506a` 接管 / 离线证据基线 `3a13bf9` / selected60 同 T·同走廊 / k=1 / 每方法新建 runtime】下，  
**【代价监督】** 相对**【原 MIQP】** 的**【单时间决策与求解链 `timing.total_ms`】** 相差**【中位 −21.5 ms（52.4 vs 73.9）；配对首成功子集中位 −25.7 ms】**。  
主要有证据因素为**【adapter 与 Gurobi Runtime 同时下降；ranking≈2.5 ms；回退单独计 15/300】**。  
原约束、首提议、回退与最终成功情况为**【接受样本残差 valid；首提议 0.700；回退后接受 0.050；最终 0.750=原方法】**。  
原始感知、在线执行和未覆盖条件分别为**【阶段2 在线请求 `total_ms` 仍更慢（并行+取消）；k=1 在线配对与“可用轨迹”边界待恢复；感知→控制消费证据缺失】**。

在【阶段2 发布镜像与历史多候选时间策略】下，  
**【代价监督】** 相对**【原方法】** 的**【规划输入→指标写出 `total_ms` p95】** 相差**【动态 +357 ms、森林 +401 ms 量级】**。  
主要有证据因素为**【`parallel_ms`/`cancel_drain_ms` 与慢请求比例，而非选中分支 Runtime】**。

---

## 6. 阶段关闭判定

| 关闭项 | 状态 |
| --- | --- |
| 旧更慢数字的字段/起止/版本 | **完成** |
| 同时间固定问题分层结果 | **完成**（selected60 复算） |
| 局部规划全链 / 规划输入→轨迹 | **部分**：阶段2 有 parallel/drain；k=1 可用轨迹对照 **未完成** |
| 候选数、生命周期、回退、调度独立证据 | **完成** |
| 更快/相近/更慢总判 + 成功率/质量/范围 | **完成（分层判定，见 §0）** |
| 可复现产物 | 本文件 + `selected60_first_vs_fallback.*` + `fresh_vs_persistent.*` + 原始 JSONL |

**判定：** 《Z分配路线耗时归因结论》作为离线主结论与在线机制解释 **正式交付**；在线 k=1 恢复列为同阶段残余测量，不重新打开“先训练”优先级。

---

## 7. 产物与复算入口

| 产物 | 路径 |
| --- | --- |
| 本结论 | `docs/request-latency-v2/evidence/analysis/Z分配路线耗时归因结论.md` |
| 总计划 | `docs/unified-plan.md` |
| selected60 分类 | `docs/request-latency-v2/evidence/analysis/selected60_first_vs_fallback.md` |
| 生命周期 | `docs/request-latency-v2/evidence/analysis/fresh_vs_persistent.md` |
| 原始重放 | `docker/dev-workspace/results/request-latency-v2/stage6/replays/selected60/` |
| 阶段2 metrics | `docker/dev-workspace/results/learning-stages-v2/stage2-isolated/jobs/*/metrics.jsonl` |

复算命令（环境健康时）：

```bash
# 离线配对（已有结果可只读复算，无需重跑）
replay_integer_planning --input …/selected60.jsonl --candidate-limit 1 \
  --bc …/bc.json --cost …/cost.json --runtime-reuse fresh
```

---

## 8. 唯一下一操作

1. 保持模型与时间策略冻结。  
2. 在线侧仅做恢复 k=1 对照所需的最小修复（空分类/不可行诊断已有 WIP 探针与 stage 字段）。  
3. 并行启动总队列第 4 项：可微硬约束 QP 时间训练验收门槛核对与实现计划（不改离线归因结论）。
