# 第一阶段整数决策学习：实施状态

2026-09-08 当前状态：固定起点重采已在 seed22 后暂停（训练 0–22，138 场）。
新协议 `benchmark_aligned_v1` 已在 `sando-integer-centered` 上启动，输出
`integer-benchmark-aligned-data/`，不得与 racefix 数据合并。规划器仍是冻结的
`fd2c5e16`；容器内已替换采集脚本。尚未训练正式模型，尚无学习收益结论。

当前执行清单：`docker/results/integer-racefix-serial-plan/plan.json`。
数值门槛报告：`docker/results/integer-pilot-centered-label-report.json`。
冻结目录：`docker/results/integer-racefix-image/`（未覆盖 `integer-centered-image`）。
以下保留实施与诊断过程；较早的阻塞状态已由后续记录更新。

## 已实现与复现

新增只读基线记录工具，使用 Python 标准库。它保存 Git 提交、工作树状态、
递归子模块版本、受版本控制文件的 SHA-256、配置文件内容标识、Docker 服务端版本与镜像标识查询结果。
未跟踪文件只列路径，不纳入内容标识；不读取授权文件。返回码 2 表示有查询失败，
但报告仍保存。即使所有查询成功，也不会自动通过后端或仿真验收。

在仓库根目录执行（输出文件必须是新路径）：

```bash
python3 scripts/capture_integer_learning_baseline.py \
  --output docker/results/integer-learning-baseline-20260907.json
python3 tests/ampl_model/test_baseline_capture.py
```

本次报告在上述 `docker/results/` 路径，按现有规则忽略，不提交生成数据。
初始受版本控制工作树干净；已有未跟踪 `.agents/`、`.codex/`、`AGENTS.md` 保留。

| 标识 | 本次值 |
| --- | --- |
| 源码提交 | `4a559609a4d1f9b75c9d373638f6c27d32542cc7` |
| 受版本控制文件数（含子模块） | 2180 |
| 文件清单内容标识 | `f79d4ab904edd5deed7fad2f859c65fa00cb1618f6c4c6782dc0109059fd207f` |
| 已验证的原始镜像 ID | `sha256:d0dc16e4318c2bcd8e8ff39dd568d019ec545c59c25acd597fdc80a06115e5b4` |

首次报告是一份源码身份记录；恢复 Docker 后另存镜像和服务端身份 JSON，保留首次失败证据。
历史文档中的通过结果与镜像标识没有冒充为本次验证。

## 本次验证与阻塞

- 基线工具检查通过：稳定内容标识、配置修改和删除可检测、拒绝覆盖旧报告、验收门槛默认关闭。
- `docker ps`：`permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`。
- `sudo -n docker ps`：`sudo: a password is required`。
- 当前进程的用户组不含 `docker`；未改 socket 权限或用户组。
- 标准路径 `/opt/ros`、`/opt/ampl`、`/opt/ampls` 不存在，不能直接替代容器运行。

用户随后提供了 sudo 授权，Docker 访问已恢复。首次 `docker exec` 没有继承入口脚本设置的
AMPL 路径，补齐 `SANDO_AMPL_EXECUTABLE`、`AMPL_LICFILE` 和 `AMPLKEY_RUNTIME_DIR`
后，真实后端五项测试通过（5/5），独立 AMPLS 探针通过，20 次全新进程冷启动并发测试通过。
基于上表不可变镜像新建独立容器后，五项测试再次通过（5/5）。
日志分别保存在 `docker/results/integer-baseline-ctest-env.log`、
`integer-baseline-preflight.log` 和 `integer-baseline-clean-ctest.log`。
密码没有写入代码或实验记录。

真实仿真发现并修复了一个前置故障：D435 网格引用包含重复的 `share/sando`，
Gazebo 图像传感器线程在远端模型数据库查找处阻塞，深度点云虽然有发布者，却没有消息。
两次同场景 100 秒观察都停在起点。调试栈和 ROS 话题观测将问题定位到资源加载，
未改动求解约束。修复 `_d435.urdf.xacro` 与 `_d435i.urdf.xacro` 的网格引用后，
实际展开的 URDF 网格检查从失败变为通过，点云探针从超时返回 124 变为收到宽度 120 的点云。

修复后同一静态未知场景（50 障碍、种子 0、动态比例 0、起点 `(0,0,2)`、目标 `(105,0,2)`）
在 50.343 秒收到到达事件，后续里程计确认终点误差 0.276 米。结果保存于
`docker/results/integer-baseline-static-meshfix/result.json`。
动态未知场景（其余相同，动态比例 0.65）在 47.850 秒收到到达事件，后续里程计
确认终点误差 0.296 米，记录为 `docker/results/integer-baseline-dynamic-meshfix/result.json`。
这项资源路径修复属于所有组共享的前置修复，不属于学习收益。

## 正在实施的下一道门槛

- `PlanningInstance` 保存完整模型、几何、时间、赋值变量与系数恢复表达式，支持版本化 JSON 往返。
- 固定整数并展开指示约束，拒绝仍有二次约束的模型；直接指定赋值的入口生成普通走廊线性约束。
- 统一实际分段时间为 `max(initial_dt, 2*dc)*factor`，同步轨迹求解、走廊时间层与最坏预测时域。
- 相关规划目标禁用 `fast-math`，以保留非有限值检查。该编译选项与时间修正应用于全部对照组，须单独复验。
- 第二次容器构建后 13/13 测试通过，包括真实后端的全部 32 个小规模候选枚举、最优 MIQP 对照、在线/离线 QP 目标与轨迹系数恢复。
- 随后新增“请求重置不得暴露旧模型”检查。第三次构建的该项失败（其余 12 项通过）：反汇编确认可执行文件仍含旧重置函数；补丁保留的时间戳导致增量构建跳过源码。强制重新编译后，第四次构建的 13/13 检查通过（9.10 秒），旧模型检查恢复正常。
- 审查又发现并修复两项已有接受流程问题：追加点过期时必须返回失败，多个已完成因子不得互相取消已选中的首个成功结果。QP 与 MIQP 的最优解统一经过同尺度残差检查；这些属于全部组共享修正。第五次构建及冻结镜像中的 13/13 检查均通过。
- 冻结采集镜像 `sando-integer-capture:f2ee7868`（ID `sha256:ddb46aedf3aa812d822c4bd42070a28087fecee2d1b33674b07dc44072ae98e4`）的静态复验于 54.758 秒到达，终点误差 0.276 米。但同一 Gazebo 消息中的机器人与障碍位置记录出现包围盒重叠；已独立复算确认，不能报告“无碰撞”。这是采样几何指标，不是物理碰撞传感器事件。
- 动态复验在转入飞行时发生 SIGSEGV，100 秒内没有位移。原始 core 的崩溃栈位于 `compileModel` 的 `getenv`，同时另一个线程正在 AMPLS 初始化。加入调试器后的同场景运行到达目标，并不能否定原始故障；驱动反汇编进一步确认该初始化路径调用 `setenv`，并且会更新 `PATH`。已让环境值复制、临时目录解析和整个 `posix_spawnp` 调用共用 AMPLS 生命周期锁；等待子进程与实际优化仍保持并行。修复版 13/13 检查及 20 次并发冷启动通过（每次 9 个独立模型）。新镜像 `sando-integer-capture:envfix1` 中 13/13 检查再次通过；静态、动态复验分别于 42.666 秒与 42.468 秒到达，终点误差 0.291 米与 0.302 米，两者均出现采样包围盒重叠。复验流程通过后启动 `integer-pilot-envfix` 的 100 实例试采。
- 证据位于 `docker/results/integer-baseline-{static,dynamic}-acceptance/`、`integer-dynamic-crash-core-stack.log`。旧基线到达结果不替代当前版本验证。

## 后续阶段的代码准备（尚未开展实验）

- 采集器采用每 episode 上限 10 的均匀蓄水池采样；补采上限 5。采集脚本校验场景划分、身份标识、重复实例和采样上限，100 实例试采不足时保存部分结果并返回失败。
- 离线标注器完整枚举候选；未知状态以 10 秒上限重试一次，仍未知的实例不进入完整代价训练。
- Python/PyTorch 训练与 Eigen 推理实现已加入。九组人工输入的一致性检查通过，最大分数绝对差约 `2.78e-16`，排序完全一致。这不是已训练模型的部署验证。
- 在线候选尝试、同因子 MIQP 回退及评测记录已接入，纳入 21 项检查；实际训练模型的闭环验证仍待开展。

100 实例试采已完成：训练种子 0–9、50 个障碍、动态比例 0.65，10 次飞行中 9 次到达、1 次超时。从 3,489 个合格实例均匀保留 100 个，每个 episode 最多 10 个；采集校验通过。91 个实例各有 243 个候选，9 个各有 32 个，共 22,401 个候选，正在完整标注。结果位于 `docker/results/integer-pilot-envfix/`。

首个标注包装脚本因镜像没有 `/usr/bin/time` 在求解前退出；保留失败日志后，改用 Python 标准库计时重新启动，未改动镜像或求解逻辑。实际标注日志为 `integer-pilot-envfix-labels-v2.log`，逐实例结果为 `integer-pilot-envfix-labels.jsonl`。

实际训练、两轮闭环补采和公平评测尚未开始。
遵守用户要求的阶段门槛，当前实现与测试通过前不扩大后续实验。

## 100 实例试采发现的数值问题

完整枚举 22,401 个候选耗时 1,386.7 秒（共享机器负载下）。整批质量核对发现：
`n50-d0.65-seed8` 请求 98、因子 7 的原 MIQP 返回最优状态和目标 `104161.6478`，
但全部 32 个固定赋值 QP 都得到约 `91659.8126`。独立高精度计算确认，
保持原整数赋值不变也能达到该较低值；不是快照变更或整数单选化造成的差异。

同一实例冷重放将原时限从 1 秒延长到 10 秒，仍返回原较差值。目标中含约
`1e15` 量级项，原 MIQP 预处理后只保留两个连续变量。参数探针中
`NumericFocus=2` 是修复该例的最小有效等级；等级 1、仅改变缩放或
`Aggregate=0` 均未修复。现已对全部方法统一设置 `NumericFocus=2`，保留
原时限、目标和硬约束，并增加该真实实例的回归检查。旧配置回归测试失败，
新配置通过；完整编译成功，21 项 CTest 全部通过（`integer-online-ctest3.log`）。
另修正旧版 JSON 库的编译兼容性及有效掩码测试夹具。尚未通过整批复验，
所以不扩大数据、训练或宣称 QP 等价性阶段完全通过。

原始标签和日志保留；数值探针设置与结果为
`docker/results/integer-numeric-parameter-sweep.json`。设置含义参考
[Gurobi 数值处理指南](https://docs.gurobi.com/projects/optimizer/en/current/concepts/numericguide/numeric_parameters.html)。


## NumericFocus 2 镜像复验

冻结镜像 ID：`sha256:79ca7cfa27c252a7ca5c0ee61732922b5e67329bba227ca83b37b36e5f1c5aa9`。
源码清单 SHA-256：`199ea787c2c1ee8cfc5b67943feb454c54d9bf2554f28f32205c282d1d2e749b`。
构建环境与全新镜像各自通过 21/21 CTest；后者日志为 `integer-online-clean-ctest.log`。

静态、动态基线分别于 45.029 秒和 45.249 秒到达目标。静态未记录采样包围盒重叠；
动态记录了重叠，首次涉及障碍 4026，仿真时刻 25.3 秒。独立复算各轴中心差约
`[0.172, 0.176, 0.488]` 米，均小于包围盒半尺寸和 0.5 米，确认是所定义指标下的重叠。
这不是无碰撞通过；此前共享修复版本也出现过重叠，不能仅凭本次单场景归因于数值设置。
结果位于 `integer-focus2-baseline-{static,dynamic}/`。

旧 100 实例的模型快照保持不变，旧求解结果保持原始来源。新参考解单独保存于
`integer-pilot-focus2-references.jsonl`：53 个最优、47 个不可行；全部最优解残差有效。
异常实例新目标为 `91659.81298217177`。新候选标签为 `integer-pilot-focus2-labels.jsonl`，
运行来源为 `integer-pilot-focus2-run-provenance.json`；仍在等待完整枚举结束后核对。

重放汇总中原方法漏计适配耗时的一行修复已写入源码，尚未纳入本镜像。
它不影响此次单独参考解程序及候选标注器；正式耗时比较前需要编译并冻结该修复。


## 整批复验仍未通过

NumericFocus 2 整批 100 实例标注耗时 1376.43 秒：53 个完整可行代价表、46 个全部不可行、
1 个含未知候选。核对再次发现已证最优 MIQP 与 QP 不一致：`seed3/request75/factor6`
的参考目标 `84339.31876288727`，全部 32 个 QP 为 `64294.33494589105`。
高精度独立核算确认，保留同一整数赋值也能达到后者；不是 QP 放松约束。

对该新反例，NumericFocus 0/1 正确，2/3 反而错误，因此不能把增大该参数视作可靠修复。
关闭 Gurobi 预处理（`Presolve=0`，NumericFocus 0）在两个已知反例均恢复正确目标。
正在将其作为下一套全组共享配置验证，并把第二个真实反例加入回归测试。
仍不扩大数据或开始训练。原始数值扫描及失败摘要保留于
`integer-focus2-numeric-parameters.json` 和 `integer-focus2-quality-failure.json`。


## 连续变量平移修复

单独关闭预处理虽然修复两个 MIQP，却让第一个固定 QP 在所有已试数值等级下返回数值失败；
该配置未通过回归检查，也未用于扩大采集。联合参数对照保留在 `integer-joint-numeric-*.json`。

改为在共享 AMPLS 入口平移连续变量：用正定二次目标的中心构造 `x=z+s`，
保留原始模型快照，对目标、全部约束和变量边界做同一替换。使用长双精度累加新常数与
线性项，保留目标常数及圆整产生的剩余线性项；求解后映射回原变量再计算原目标、检查原约束。
不支持的目标或平移导致边界坍缩时保留原表示。Gurobi 恢复共享默认数值配置
`NumericFocus=0, Presolve=-1`；原时限和容差不变。

构建成功，24/24 检查通过（`integer-centered-ctest.log`），包含两个真实反例、
多点表达式替换、极端边界保护，以及两次请求中心变化时的持久复用与独立重导入验证。
这只通过了回归门槛；新镜像仿真和 100 实例整批复验仍需完成。


平移版镜像为 `sha256:b5ceb87b1968d4ea38fa2f81ba16128a06a46807aa12d3289f27f7f5811527a4`，
源码清单 SHA-256 为 `511eb91de14a88a4b03a8d5081b323393469ef0c2c878394f12fd32f4956ce3f`。
首次新容器检查早于许可证激活，两个较早运行的测试遇到演示许可证规模限制；
启动完成后完整 24/24 通过（`integer-centered-clean-ctest2.log`），保留首次失败日志。
静态、动态场景分别在 47.648 秒和 45.761 秒到达，动态仍记录采样包围盒重叠。

新 100 个 MIQP 参考解完成：53 最优、47 不可行，最优解残差均有效。
两个反例的目标分别恢复至约 `91659.812882` 和 `64294.334969`。
本次完整标注采用 4 个独立进程，按连续实例分片；每个实例的全部候选仍由原标注器完整枚举，
每次求解线程数、时限及重试规则不变。总计时、进程并行度、输入输出及程序哈希单独记录，
不将相对旧串行标注的耗时变化解释为学习收益。并行说明为 `integer-pilot-centered-parallel.json`，
标注辅助脚本为 `docker/results/label_integer_shards.py`，其成功与失败路径已做小规模验证。


## 平移版整批门槛通过；正式采集调整

100 实例、22401 个候选已完成标注：52 个完整可行代价表、45 个全部已证不可行、
3 个包含未决候选而排除。全部 52 个可比最优目标与 MIQP 一致，最大缩放差
为 `3.72599e-9`；45 个全不可行实例也一致，无可判定矛盾。3 个未决实例不作等价性
通过结论。报告、完成记录分别为 `integer-pilot-centered-label-report.json` 与
`integer-pilot-centered-completion.json`，后者绑定输入输出、程序、运行配置及退出码。
四进程离线标注墙钟 424.554 秒，求解配置保持一致；该并行收益不归因于学习。

随后四路 Gazebo 采集出现明显的墙钟超时变化，已停止新增场景并等待当前飞行清理完成。
`integer-centered-data/worker{0,1,2,3}` 仅保留为负载诊断，不进入正式训练。
正在用相同 seed0、50 障碍静态场景单独复测快照采集，区分采集开销与并发负载影响。
后续正式采集采用串行，不放宽 100 秒观察上限，也不减少 240 训练/60 验证场景矩阵。
旧 100 实例仅保留为数值验证证据，正式数据全部重新在最终共享后端采集。
尚未开始正式模型训练、闭环补采或最终测试，不能据此声称学习收益。

单独开启快照的静态 seed0 场景在 56.729 秒到达，无采样碰撞（`integer-centered-isolated-capture-static`）。
已启动串行正式采集，执行清单为 `integer-centered-serial-plan/plan.json`，
逐种子保存六种场景和独立汇总，输出为 `integer-centered-serial-data`。


## 离线训练批量计算验证

冻结的在线 Python 特征实现和 C++ 推理保持一致；离线增加参数无关的几何缓存，
将同一 minibatch 的平面编码与候选 MLP 分别批量计算。保留全部平面、逐走廊 mean/max、
float64、逐实例 softmax、损失权重、Adam、种子和 epoch 设置。验证集分块为 32，
仍按同一前三候选规则选择最早最佳 checkpoint。实现与依赖身份单独记入模型元数据。

独立检查覆盖 32、72、243 个候选、空掩码、全部平面、分数、梯度、一次 Adam 更新、
同分排序、赋值顺序拒绝及验证指标；现有策略检查通过，独立审查未发现实质性问题。
矩阵批量计算只要求数值一致，不承诺 100 个 epoch 的权重或近同分 checkpoint 与旧循环逐位相同。

仿真暂停期间以 52 个可用 pilot 实例作性能工作负载，预热后测三次：
训练步骤中位数 `2274.694 → 660.234 ms`（3.445 倍）；缓存验证 `779.502 → 209.280 ms`；
一次缓存准备 `159.768 ms`。最大分数差 `1.388e-16`、梯度差 `2.168e-17`、
两批 Adam 更新后参数差 `9.472e-13`，验证指标差 0。保留此 CPU 实现。
报告为 `integer-training-batch-benchmark.json`，决策与脚本身份为
`integer-training-batch-decision.json`；复现脚本为 `bench_integer_training_batch.py`。
这些均不是正式模型训练或在线规划收益。测试工作负载不进入正式数据。


## 串行采集发现内存崩溃，已暂停

seed0 六个场景全部到达，保留 60 个实例。seed1 的 50 障碍动态场景在约 12 秒后
规划器因 `double free or corruption (out)` 退出（SIGABRT，ROS 启动日志退出码 -6），
采集器仍观察到 100 秒后记录任务超时。不能将该崩溃仅归为普通规划失败。
随后 seed1 第三个场景结束，父采集进程已暂停，不再启动后续场景。

从系统转储取得的堆栈显示：`free → vector<RobotState>::_M_realloc_insert →
publishActualTraj → stateCallback`。状态订阅目前允许回调重入，而实际轨迹历史和
发布节流状态没有独立同步；这是待验证的竞态假设。其他线程在释放 JSON 的事实本身
不足以证明快照采集器是根因。相同场景再次运行在 55.35 秒到达，故故障具有间歇性。
证据为 `integer-centered-abort-stack.log`、原失败 episode 的 `tmux.log`、
以及独立复跑 `integer-centered-abort-repro1`。正在建立更短的实际节点压力测试。

## 崩溃已复现并修复；开始全量重采

根因已用真实 ROS executor 与 `/NX01/state` 压力回路确认：`stateCallback` 与
`trajCallback` 原先同属 Reentrant 组，`publishActualTraj()` 无锁改写
`actual_traj_hist_`。修复前 3 次中 2 次以退出码 -6 结束，日志为
`double free or corruption (!prev)`（原飞行为 `(out)`，同类 allocator abort）。
记录：`integer-state-pressure-before.json`、`integer-state-pressure-installed/`。

最小修复：仅把状态订阅放到未使用的 MutuallyExclusive `cb_group_mu_1_`；
`/trajs` 与 `predicted_trajs` 仍留在 Reentrant 组。修复后压力 8/8 均
`state_initialized_count=1` 且无 abort（`integer-state-pressure-after/`）。
共享 CTest 24/24，28.19 秒（`integer-state-racefix-ctest.log`，未覆盖旧
`integer-centered-ctest.log`）。原 seed1 动态场景复跑 68.96 秒到达，终点误差
0.327 米，tmux 无 double free；仍记录采样 AABB 重叠，不能称无碰撞
（`integer-state-racefix-seed1/`，当时 `source_id` 仍为旧
`511eb91de14a88a4b03a8d5081b323393469ef0c2c878394f12fd32f4956ce3f`）。

安装节点哈希 `75c502654d845224af5a886268b605d9cdfe142aa3a3fbb48f4bde4fe599d786`。
源码 `sando_node.cpp` SHA-256
`64dd3585d7445a6b834a5f106d49b7229f7620d7cf13f65796e336200cfb10a0`。
已在新目录冻结：`integer-racefix-image/`，manifest SHA-256
`fd2c5e160174bf81e58a5597c652930c860a6ab697b9b47177d48c3d82a1977c`。
未覆盖 `integer-centered-image` 或旧采集标签。

旧串行采集父进程已 SIGTERM 结束（退出码 143），pause 文件仍在；不要 CONT 恢复。
`integer-centered-serial-data` 的 seed0 与崩溃 seed1 只作证据，不进入训练。
正式数据在 `integer-racefix-serial-data` 全部串行重采：训练种子 0–39、验证
100–109，每种子 50/100/200 障碍 × 静态/动态 0.65，每 episode 最多 10 条，
观察上限 100 秒，`physics_concurrency=1`。测试集仍锁定。

截至 2026-09-08 04:05 UTC，`plan.json` 状态为 `running_round0_serial_recapture`。
镜像 `sando-integer-capture:racefix1`（`sha256:c2a5ceed…`），`source_id`
`fd2c5e160174…`，安装节点 `75c502654d84…`。已完成：
seed0 六场全部到达（57–81 秒），seed1 六场全部到达（57–约 80 秒），
含原崩溃场 `seed1_n50_d0.65`（64.425 秒，goal 到达，无 `double free` /
`exit code -6`）。已完成场景的 `tmux.log` 扫描无 allocator abort。
seed2 已完成 n50 静态，正在飞 n50 动态。验证集尚未开始。
需要暂停时放 `docker/results/integer-racefix-serial-plan/pause`。
300 个场景完成前不开始标注或训练。
