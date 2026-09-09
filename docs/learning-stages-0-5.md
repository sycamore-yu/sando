# SANDO 阶段 0–5 实施与验收

2026-09-08，用户授权执行完整架构报告的阶段 0–5。目标是实际采集 → 专家完整代价表 → 完整走廊赋值网络 → 固定赋值硬 QP → 原约束验收，并公平比较 BC、代价监督、集合监督与不使用专家标签误差的目标训练。报告基点为 `6698fcf`。完成实验不等于学习方法胜出。

阶段 0–5 的实施、实际实验与验收已完成；失败、条件性重试和实验局限均保留报告。所有本轮原始证据位于 [`learning-stages-v2`](../docker/dev-workspace/results/learning-stages-v2/)。

## 验收状态

| 阶段 | 实施与证据 | 状态 |
| --- | --- | --- |
| 0：可靠标注 | 文件锁覆盖 worker 与存活求解子进程；领取/恢复/发布互斥；完整输入身份、模型身份与输出校验；300 个任务、3000 个实例全部交付；未知与不可行分别统计 | 已完成 |
| 1：开发与采集 | 宿主机编辑/容器构建/测试、冻结镜像；独立 1/2/4 worker 实测；修复并验证 ROS 并行域串扰与森林碰撞几何 | 1/2/4 worker 吞吐、RTF、内存、延迟与失败率实测完成 |
| 2：公平训练及闭环 | 同语料、特征、float64、100 epoch、batch32；4 种方法各 3 个训练种子；全验证集 Top‑3 评估；验证集选模型后冻结 | 训练、离线、216 次有效在线运行及配对统计完成 |
| 3：两轮 DAgger | 每轮学生访问状态和原专家状态各 48 次完整表查询；原始/新数据按 50:50 采样；每个对照各 3 个训练种子，验证集选模型 | 两轮采集、192 个补标实例、12 次训练及 72 次最终在线运行完成 |
| 4：真实轨迹模式 | 3000 个实例完整扫描；25 个位置采样、0.05/0.1/0.5 m 阈值；12 个模型 Top‑3 覆盖 | 已完成模式与覆盖测量；本语料未触发近优多模式多头实验 |
| 5：时间分配/FM | 回归及条件 Flow Matching 各 3 个训练种子；NFE 1/4/8；时间变化后逐候选重建走廊、硬 QP 与残差验收；真实隔离预检 8/8 | 训练、实现、预检、144 次正式运行及配对统计完成 |
| 原目标/RAYEN | ADR0003 禁令由 ADR0006 取代；原始 QP 目标训练；48 个实际实例运行 RAYEN 梯度、可行性与 QP 差距实验 | 可行性评估完成，不能宣称可替代 QP |

## 冻结协议与运行身份

协议：[`study_protocol.json`](../docker/dev-workspace/results/learning-stages-v2/study_protocol.json)。训练 seeds 0–39，验证 100–109；本轮测试固定 200–205，共 6 个 seed × 6 类场景。未知动态为 50/100/200 障碍，只使用机载可见信息；静态森林为 easy/medium/hard，重复的森林地图不能当成独立新地图。

本轮正式方法比较统一使用镜像 `sando-learning-release:595ab0d8c31f9a48ebba`，不可变 ID：

```
sha256:b857ff8584ede4d71feb24503615c5e3b7e564a726f54ca62099e534aa965761
```

[`isolation-release.json`](../docker/dev-workspace/results/learning-stages-v2/isolation-release.json) 保存完整源码清单、父镜像和 Python 修补范围。编译产物继承已验证父镜像；该镜像实际运行的 CTest **34/34 通过**，日志为 [`isolation-release-ctest.log`](../docker/dev-workspace/results/learning-stages-v2/isolation-release-ctest.log)。时间模型 Python/C++ 实值一致性误差不超过 `5.6e-17`，并验证非法特征、标准差、分位点与残差路径。

两组仿真各 2 个 worker，CPU 集合互不重叠，各含 8 个物理核、16 个逻辑核，NUMA 核数构成相同。主组运行基础/最终 DAgger 评测，辅助组顺序运行 DAgger 采集和时间策略评测；训练和标注固定其余 4 个物理核。每个实例仅有一个本地规划器，ROS 限于容器 loopback，并设置独立域。查询成本既报告实例数，也报告实际求解尝试数。

## 阶段 0：完整交付与标签质量

原始采集的 40 个训练 seed 和 10 个验证 seed 全部完成。隔离目录 `seed33.invalid-segfault` 被排除，未混入快照。每个快照文件均有复制前后哈希校验；300 个标注任务对应 3000 个实例，全部任务成功交付并严格合并。

| 划分 | 总实例 | 有完整且至少一个可行候选 | 所有候选已证不可行 | 含未知/不完整求解结果 |
| --- | ---: | ---: | ---: | ---: |
| 训练 | 2400 | 1479 | 872 | 49 |
| 验证 | 600 | 379 | 204 | 17 |

“3000 个实例交付成功”不表示所有实例可行。未知求解结果不填成零成本，也不伪装成已证不可行。标签保存完整赋值、实际轨迹系数、原始 jerk 目标和验收残差，避免只比较离散赋值字符串。

原始采集隔离审计覆盖实际用于训练/验证的 300 次运行，排除隔离目录内的 5 次旧失败采集；每次记录一个目标订阅者，记录的目标观察时间区间无重叠。旧采集版本没有 `simulation_health` 字段，证据限于订阅者、运行错误与时间记录，详见 [`original-capture-isolation-audit.json`](../docker/dev-workspace/results/learning-stages-v2/original-capture-isolation-audit.json)。

## 阶段 1：实际并发校准

同四个训练 seed、每 seed 两类场景，每次飞行最多保留 5 个实例；三组分别独立运行。分母为外部实际墙钟，而非各飞行时间之和。

| worker 数 | 实际墙钟 s | 有效实例/h | 健康飞行 | 到达目标 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 653.49 | 220.36 | 8/8 | 8/8 |
| 2 | 364.69 | 394.85 | 8/8 | 8/8 |
| 4 | 211.93 | 679.47 | 8/8 | 7/8 |

首次校准保留如上；完整资源校准使用包含启动修复的 `calibration-release.json` 镜像，在所有正式仿真与独立预检完成后，按同样四个 seed、两类场景、每飞行最多五个保留实例，独立顺序运行 1/2/4 worker。三组共 24/24 个健康且完整记录的仿真观察。

| worker | 墙钟 s | 完整交付 seed | 交付有效实例/h | 到达 | RTF 中位数 | 最大单容器峰值 GiB | 请求 P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 634.06 | 4/4 | 227.11 | 8/8 | 0.608 | 1.596 | 681.2 |
| 2 | 356.77 | 3/4 | 302.72 | 7/8 | 0.613 | 1.601 | 717.6 |
| 4 | 173.26 | 4/4 | 831.13 | 8/8 | 0.550 | 1.555 | 1117.4 |

全部 24 次运行都有 RTF、规划延迟和资源记录，三个组共 12 份容器内存峰值。RTF 来自同一观测样本的仿真时间/单调墙钟时间跨度，样本跨度覆盖至少 96.1% 的飞行观察时间；内存是每个 seed 容器的 cgroup 生命周期峰值，表中取组内最大值，未声称测得全机并发总峰值。成功规划请求 P95 分别为 813.7/917.7/1272.8 ms，避免将快速失败请求误作求解加速。

2 worker 的一次健康运行停在规定的非零起点并超时，没有有效捕获实例，具体原因未确立；它不符合已知的原点跳变特征，因此保留为校准失败而不重试。该组原始保留 35 个实例，但一个 seed 的采集包未完整交付，仅 30 个实例计入有效交付吞吐；原生退出码 2、3/4 交付率及 1/8 超时率均保留。1/4 worker 均交付 40 个实例，超时率为 0/8。观察完整、采集包完整交付和飞行到达是不同指标。

4 worker 的交付吞吐约为 1 worker 的 3.66 倍，但 RTF 较低、规划尾部延迟较高；不能据这一小样本宣称增加并发改善单次规划质量。完整结果见 [`worker-resource-calibration-summary.json`](../docker/dev-workspace/results/learning-stages-v2/worker-resource-calibration-summary.json)。第一组曾因 root 所有的指标日志不可读而停止汇总；修正导出权限前后八份日志的内容哈希相同，原飞行时间、资源记录及采集收据未改动。后两组采用相同仿真镜像，仅在捕获结束后调整日志读取权限；修补差异与哈希保存在 `calibration-runner-v2/`。

### 已发现并排除的串扰

第一版通用在线驱动遗漏 ROS 隔离；并行容器共用域 42，在 Docker bridge 上互相发现。旧预检的目标订阅者为 4，初始正式批次为 2–4，甚至出现“成功到达却没有本地规划指标”。这属于无效实验，不能作为算法成功或失败。

`timing-online-pilot`、`stage2-online`、`dagger-student-r1` 全部保留并写入 `INVALIDATED.json`，汇总与补标入口直接拒绝。修复同时进入正式 Python 启动器与通用驱动：localhost-only、单规划器准备检查及观察期间多规划器拒绝。重做的 [`timing-pilot-isolated`](../docker/dev-workspace/results/learning-stages-v2/timing-pilot-isolated/) 共 8 次，健康和到达均为 **8/8**，每次只有一个规划器；不计入测试集。新的正式结果只取当前冻结计划中已验证 ROS 隔离的批次：`stage2-isolated`、`timing-isolated` 及 `dagger-{student,control}-r2-evaluation`。

### 采集期间发现的启动顺序缺陷

第二轮学生 seed32 的首次森林 easy 采集，在收到正确起点后约 0.02 s 跳到了原点，未生成任何规划实例。代码与真实规划器回归测试确认：终点先于首条状态到达时，旧实现从默认零状态初始化 YAWING 悬停点，首条真实状态又沿用了这个零点。新实现暂存早到的终点，用同一个锁串行处理状态与终点初始化，在真实状态到达后应用最后一个待处理终点。目标先到、状态先到、多个早到终点及同时起跑的线程竞争测试均已通过。

独立修复镜像为 `sando-learning-release:e3f6147e883a6ebb6be0`，不可变 ID `sha256:468496d41e7aa4c02b60c0a5f5767c020c697001073a544e15fa5f6c5a072d6e`。该镜像实际运行的 CTest **35/35 通过**，见 [`startup-release-verified.json`](../docker/dev-workspace/results/learning-stages-v2/startup-release-verified.json) 和 [`startup-release-ctest.log`](../docker/dev-workspace/results/learning-stages-v2/startup-release-ctest.log)。独立在线预检已完成 **8/8 正常到达**，每次仅有一个规划器，8 份起点轨迹均无已知异常，见 [`startup-pilot-startup-audit.json`](../docker/dev-workspace/results/learning-stages-v2/startup-pilot-startup-audit.json)。

本轮公平比较保持原冻结镜像。失败 seed32 整体归档后，使用相同镜像、模型、seed 和采集预算重试；另外三个有效 seed 的完成收据哈希未变化。重试的六场景均完成，原失败及其中五个已有场景保留在 `attempts/`，未把这些重复采集实例额外算作专家查询。详细记录见 [`dagger-r2-startup-recovery.json`](../docker/dev-workspace/results/learning-stages-v2/dagger-r2-startup-recovery.json)。因此不能声称本轮采集毫无启动失败，也不能将修复后的版本与原版本性能混在同一比较中。

## 阶段 2：同协议训练及验证

4 种方法 × 3 个训练种子已各完成 100 epoch。模型只按验证集目标指标选择，未根据测试飞行结果选取。精确身份与所有候选见 [`selected-models/selection.json`](../docker/dev-workspace/results/learning-stages-v2/selected-models/selection.json)，12 个模型全验证集结果见 [`offline-evaluation/full-validation.json`](../docker/dev-workspace/results/learning-stages-v2/offline-evaluation/full-validation.json)。

| 方法 | 选中训练 seed | 验证 Top‑3 至少一个可行 | 验证 Top‑3 近优命中 |
| --- | ---: | ---: | ---: |
| BC | 1 | 94.20% | 87.07% |
| 代价监督 | 2 | 97.63% | 95.25% |
| 集合监督 | 0 | 98.94% | 96.04% |
| 纯目标训练 | 1 | 98.68% | 95.78% |

分母为 379 个完整可用验证实例；全不可行与未知实例的数量另列，不能靠排除后百分比宣称整体可行率。部署按排名依次尝试固定赋值 QP，必要时回退原求解器；Top‑3 内最优成本是离线 oracle 指标，不代表在线实际选择。

纯目标训练优化由真实固定赋值 QP 代价表给出的期望原目标，不加入专家标签误差；它仍需要求解器代价数据，不是“无需任何求解”。软概率的梯度不能被误写成离散 argmax 或硬 QP 的连续反向传播。

### 阶段 2：完整在线结果

每种方法各 36 次飞行，动态/森林各 18 次。延迟统计覆盖目标观察窗口内实际尝试规划的请求。完整 P50/P95/P99、场景配对置信区间、跟踪误差与回退统计见 [`final-reports/stage2.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/stage2.json)。

| 方法 | 首轮到达/36 | 修正后到达/36 | 采样 AABB 重叠/36 | 动态 P95 ms | 森林 P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原求解器 | 35 | 35 | 32 | 708.7 | 409.6 |
| 前次赋值 | 33 | 33 | 31 | 1140.1 | 874.7 |
| BC | 36 | 36 | 31 | 1115.6 | 776.3 |
| 代价监督 | 33 | 34 | 30 | 1066.0 | 811.0 |
| 集合监督 | 32 | 33 | 31 | 1133.8 | 778.3 |
| 纯目标训练 | 32 | 32 | 32 | 1056.8 | 881.4 |

“首轮”保留未修正启动缺陷的整机结果；“修正后”仅替换明确起点损坏或指标不完整的运行，普通飞行失败仍保留。所有修正保持同一冻结镜像、模型、场景和资源预算。该比较以有效起点为条件，不能据此宣称原版本没有可靠性缺陷。

总计 **18,278/18,278 条接受轨迹均有硬约束残差检查，超限 0 条**，接受轨迹目标记录缺失 0 条。这仅证明检查到的局部轨迹满足原模型约束，不能替代飞行安全结论。采样 AABB 重叠率较高，尤其森林采用圆柱外包盒；保留这一保守几何观测及其局限。

当前结果不支持学习方法整体优于原求解器。BC 到达 36/36，但样本有限，配对区间不足以支持稳定的成功率提升。所有学习方法在动态和森林场景的 P95 均高于原求解器，对应场景配对差值的 95% 区间均为正。纯目标训练森林到达 14/18，说明离线目标指标改善不足以保证闭环质量。

起点异常曾使代价监督动态场景和集合监督森林场景出现约九千个无实际求解尝试、低于 1 ms 的失败请求，错误压低汇总 P50。针对性重跑后，这两个 P50 分别为 283.4/14.5 ms。保留首轮报告于 `final-reports-before-startup-correction-1788906088/`；最终按接受/失败请求拆分的复核见 [`stage2-latency-outcomes.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/stage2-latency-outcomes.json)。

## 阶段 3：两轮闭环

每个分支每轮使用训练 seed32–35，各 6 场景、每飞行 2 个实际访问状态，共 48 次专家完整表查询。学生分支首轮使用选定的 cost 模型，第二轮必须使用第一轮重新训练后按验证集选定的模型。等预算对照每轮重新采集原求解器访问状态，两轮均重新训练，不把同一批原始数据重复计作新查询。

数据、模型、图像和捕获回退身份由每个任务完成收据及不可变快照关联；补标严格验证 4 个 seed、24 个场景运行、48 个不同实例。原始与累计新增数据按 50:50 构造训练批次。测试阶段比较基础 cost、第二轮学生和第二轮等预算对照；第一轮不参与测试选模。

第一轮学生分支已完成 24 个标注任务、48 个实例：29 个可用、18 个全部候选已证不可行、1 个含未知结果。10,820 个候选表项对应 10,828 次实际求解尝试（包含 8 次重试）。查询次数相等不代表求解次数或墙钟相等，最终按两个分支分别报告。

第一轮专家对照同样完成 48 个实例：30 个可用、17 个全部候选已证不可行、1 个含未知结果，实际求解尝试也是 10,828 次。两个分支的三个训练 seed 均完成 100 epoch；学生选中 seed1，对照选中 seed2。第二轮学生采集使用了第一轮学生的新模型，已核验模型哈希。

第二轮学生分支 48 个实例中，34 个可用、14 个全部不可行，实际求解 9,765 次；专家对照 27 个可用、21 个全部不可行，实际求解 11,242 次。两轮累计学生/对照均查询 96 个实例，但实际求解分别为 **20,593/22,070 次**，可用实例分别为 **63/57 个**。第二轮两个分支各三个训练 seed 均完成 100 epoch，验证集分别选中 seed1/seed2。输入收据、50:50 采样、12 个模型的完整训练与哈希验证见 [`dagger-training-verification.json`](../docker/dev-workspace/results/learning-stages-v2/dagger-training-verification.json)；查询细账见 [`dagger-query-budget-summary.json`](../docker/dev-workspace/results/learning-stages-v2/dagger-query-budget-summary.json)。

### 两轮 DAgger 的最终对照

| 方法 | 首轮到达/36 | 修正后到达/36 | 采样 AABB 重叠/36 | 动态 P95 ms | 森林 P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 代价监督 | 33 | 34 | 30 | 1066.0 | 811.0 |
| 两轮 DAgger 学生 | 33 | 35 | 32 | 1016.8 | 774.5 |
| 等查询预算专家对照 | 35 | 36 | 31 | 823.5 | 603.8 |

学生相对基础 cost 的 P95 差值区间跨零；等查询预算专家对照相对基础 cost 的 P95 差值的 95% 区间在两个环境中均小于零。直接比较学生与专家对照，学生 P95 高出动态 **193.3 ms [129.8, 271.1]**、森林 **170.7 ms [118.0, 222.1]**。因此本轮没有证据表明学生访问状态的 DAgger 优于同查询预算的新专家状态补充；不能将新增训练数据的收益归给 DAgger 机制。

完整结果见 [`dagger.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/dagger.json)，直接配对对照见 [`dagger-vs-expert-control.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/dagger-vs-expert-control.json)。等查询预算不等于完全相等的求解成本，两个分支实际 QP 尝试数已单独报告。

## 阶段 4：模式证据与多头决策

用每条实际轨迹的 25 个采样位置进行按目标排序的贪心聚类。近优条件为原目标相对容差 1%、绝对容差 `2e-6`，并报告不同空间阈值。

| 距离阈值 | 训练近优多模式实例 | 验证近优多模式实例 |
| --- | ---: | ---: |
| 0.05 m | 10/1479 | 5/379 |
| 0.1 m | 0/1479 | 0/379 |
| 0.5 m | 0/1479 | 0/379 |

所有可行候选中存在不同轨迹模式，但大部分不是近优模式。以预定 0.5 m 阈值及 0.1 m 敏感性检查，当前每个可用实例只有一个近优轨迹模式；集合模型 Top‑3 近优覆盖为 96.04%。本轮缺乏足够的不同近优专家目标来支撑 Hungarian 多头实验，因此未用复制单标签制造多模态。0.05 m 下少量差异保留报告，不能声称任意精度下完全无多模式。若新增数据出现稳定且覆盖不足的多近优模式，应重新触发多头实验。

两轮 DAgger 的 192 个新增实例亦已扫描，120 个完整可用实例在上述三个阈值下均只有一个近优模式；全部可行候选在 0.5 m 下有 12 个多模式实例，但这些额外模式不在近优集合内。新增数据未触发多头实验条件。证据及四个语料各自的哈希见 [`mode-coverage-dagger-all.json`](../docker/dev-workspace/results/learning-stages-v2/mode-coverage-dagger-all.json) 与 [`mode-coverage-dagger-provenance.json`](../docker/dev-workspace/results/learning-stages-v2/mode-coverage-dagger-provenance.json)。两个分支具有各自的状态语料，汇总时按分支/轮次保留身份，未将它们混为同一条训练记录。

## 阶段 5：时间分配与 Flow Matching

回归与条件 Flow Matching 使用相同输入、数据划分及声明域 `[1,5]`，各 3 个训练 seed，按验证集代理指标选定回归 seed0、FM seed2。每请求均提出 3 个时间因子，每因子整数 Top‑3；FM 测 NFE 1/4/8，总网络调用数为 `3×NFE`，回归一次前向给出 3 个候选。每个候选时间改变后重新构造对应走廊，再执行硬 QP 与原约束验收。

实际训练记录的时间因子支撑为 `[1,2.5]`；超过 2.5 的提议属于外推，没有隐式裁回数据区间。多数捕获请求仅有一个时间因子，验证中仅 29 个请求有配对因子证据，因此离线最近因子成本差只用于选模和说明局限，不能当成连续时间最优证明。

已验证运行指标包含网络推理、走廊构造、候选 QP、回退、取消等待、验证和总墙钟；接受轨迹的原始 jerk 目标与总轨迹时长从对应成功求解尝试提取。它们是局部规划轨迹指标，不是整次飞行的积分 jerk。

### 时间策略的最终结果

| 方法 | 首轮到达/36 | 修正后到达/36 | 采样 AABB 重叠/36 | 动态 P95 ms | 森林 P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 代价监督 | 33 | 34 | 30 | 1066.0 | 811.0 |
| 时间回归 | 35 | 35 | 33 | 703.1 | 590.7 |
| FM NFE1 | 35 | 35 | 31 | 709.7 | 577.0 |
| FM NFE4 | 31 | 31 | 30 | 688.8 | 596.8 |
| FM NFE8 | 33 | 35 | 32 | 684.3 | 554.0 |

时间策略相对基础 cost 的 P95 均降低，但该比较同时将原时间搜索改为三个学习提议，不能把收益单独归因于 FM。更直接的同提议数对照中，所有 FM 相对回归的 P95 差值 95% 区间均跨零；NFE4 的到达次数反而下降。当前没有证据支持增加 NFE 可稳定改善闭环表现，也没有证据支持 FM 稳定优于更简单的时间回归。

真实指标核验每请求三个时间提议，FM 的网络调用数严格为 `3×NFE`，回归为一次；中位推理开销约为回归 0.058–0.066 ms、FM NFE1/4/8 分别 0.094/0.192/0.31 ms。FM 接受的局部轨迹目标中位数较低，但对应访问状态、接受集合和时长也变化，因此这不是整次飞行 jerk 改善的证据。

结果与目标代理指标见 [`timing.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/timing.json)，同提议数直接对照见 [`timing-vs-regression.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/timing-vs-regression.json)。

## RAYEN：可行性与限制

6 类场景每类各选 4 个训练和 4 个验证实例，共 48 个真实实例。固定离散赋值后，将原模型的目标和线性约束转为 RAYEN 支持的连续凸集合，运行实际包、非零梯度和梯度下降；没有以伪造线性约束或常量零梯度替代。

48/48 个实例运行成功且有非零梯度。返回点的最大约束残差小于 `6e-11`。最好迭代点相对原 QP 最优目标的中位差距为训练 **+228.0%**、验证 **+198.7%**；RAYEN 迭代部分中位墙钟约 0.362/0.340 s，约束转换另计。证据支持“固定赋值后可构造可微可行映射”，不支持“当前设置可替代 QP”或“跨离散走廊并集天然可微”。该实验是逐实例可行性/优化实验，不是已训练的共享轨迹预测网络。

## 全部正式结果与边界

基础 216 次、时间策略 144 次、最终 DAgger/专家对照 72 次，共 **432 次不同正式飞行**。三个比较报告复用同一基础 cost 的 36 次运行，汇总去重后，共 **44,755 条接受轨迹全部完成原约束残差验收，超限 0 条，目标记录缺失 0 条**。每次飞行均有规划延迟数据。核验见 [`verification-summary.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/verification-summary.json)。

完整起点审计发现六次明确的“正常起点→原点→持续停在原点”异常：基础两次、时间策略两次、学生一次、专家对照一次；另有学生一次未产生规划指标。七次原始失败运行全部保留，同协议重试后正常到达；其余 426 份已完成收据哈希不变（指标缺失的运行原本没有有效完成收据）。首轮整机到达 403/432，修正后有效起点到达 410/432；这些汇总用于披露运行可靠性，各方法比较仍按场景配对，不能将混合方法的汇总当成一个算法的成功率。见 [`formal-attempt-accounting.json`](../docker/dev-workspace/results/learning-stages-v2/final-reports/formal-attempt-accounting.json)、[`formal-startup-repair-verified.json`](../docker/dev-workspace/results/learning-stages-v2/formal-startup-repair-verified.json) 与 [`formal-startup-final-audit.json`](../docker/dev-workspace/results/learning-stages-v2/formal-startup-final-audit.json)。

置信区间以场景 ID 配对重采样，未把重规划帧当独立飞行样本。仅有六个测试 seed，森林地图跨 seed 重复，独立性和外推能力有限；这些探索性比较不足以证明广泛泛化或安全性。

在线 `collision` 字段记录同一采样时刻机器人与障碍物的轴对齐包围盒重叠，称为“采样 AABB 重叠”。森林圆柱使用外包 AABB，属于保守几何判据；它不等于物理接触，也不能证明采样间隔内无碰撞。到达目标、硬 QP 约束通过和这个重叠指标分别报告，不互相替代。

复现所需的场景计划位于 `plans/`，验证集模型选择和每个候选模型的哈希保存在 `selected-models/` 及各 `*-training/selection.json`，每个研究目录的 `study.json`、`completed.json` 和 `attempts/` 关联原始运行与异常重试。`study_driver.py --resume` 只复用身份与产物哈希一致的完成任务；对已完整的目录运行会核验复用而不重新飞行。新实验须使用新输出目录并保留新的配置身份。

最终源码冻结及不可变镜像身份见 [`final-release.json`](../docker/dev-workspace/results/learning-stages-v2/final-release.json)，镜像实际测试收据见 [`final-release-verified.json`](../docker/dev-workspace/results/learning-stages-v2/final-release-verified.json)。开发容器构建、完整测试和源码同步状态分别保存在 `final-dev-build.log`、`final-dev-ctest.log`、`final-dev-status.json`。正式实验镜像与最终源码镜像的身份分别保留，不混合宣称性能。
