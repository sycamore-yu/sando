# process_improvement_v1 执行报告

配置：`scripts/process_improvement_v1.json`。核对版本：`06d11edf0c5b04b61365e5a2eb4e0c6362713abf`。正式采集未中断。

## 假设判定

| 目标 | 判定 | 依据 |
|---|---|---|
| 1. 开发修改能直接编译、测试、运行，身份清楚 | **部分支持** | 宿主编辑对容器可见；AMPL/Gurobi 探针通过；`install-dev` 二进制已产出（SHA `8b1717e2…` ≠ 正式 `75c50265…`）；增量编译与 `dev-test`（13/13）通过。尚未用开发二进制做正式飞行（正式采集仍用冻结节点） |
| 2. 同样数据质量下提高每小时有效标注实例数 | **尚未支持或反对** | 只测了采集独占吞吐。正式采集仍在写，未并跑标注，也未改正式每场 10 条 |
| 3. 多解监督与学生状态补标改善候选/回退/导航 | **尚未支持或反对** | 损失与数据入口已实现并单测。完整标注表、A/B/C 对照、DAgger 闭环都还没有真实数据结果 |

代码完成 ≠ 性能提升。下面数字只描述当前机器上的采集现状和开发通路。

## 阶段零：只读核验

- 分支 `feat/ampl-gurobi`，HEAD `06d11edf0c5b04b61365e5a2eb4e0c6362713abf`。
- 正式容器 `sando-integer-centered`：镜像 `sando-integer-centered:20260907` / `sha256:b5ceb87b1968…`。挂载只有 AMPL uuid 和 `docker/results → /results`。**不挂宿主源码。**
- 规划器身份仍是 `fd2c5e16…` / `75c50265…`。
- 当前写入者：`capture_integer_learning_campaign.py --protocol benchmark_aligned_v1`，输出 `docker/results/integer-benchmark-aligned-data/`。
- 协议：train/val 起点 `train_box_v1`，场景族 `unknown_dynamic` + `static_forest`。测试评测仍是 `(0,0,2)→(105,0,2)`。
- 旧数据不得并入：`integer-racefix-serial-data`、`integer-centered-serial-data`、四路 worker 目录、pilot 标签。
- 尚无正式模型文件。pilot 标签在 `docker/results/` 下，仅诊断。

路径对应：

| 宿主 | 容器 |
|---|---|
| `/home/tong/tongworkspace/dockerworkplace/sando` | `sando-dev:/root/sando_ws/src/sando` |
| `docker/dev-workspace/{build,install,log,python,results}` | `/root/sando_ws/{build-dev,install-dev,log-dev,dev-python,dev-results}` |
| `docker/results` | `sando-integer-centered:/results` |

## 阶段一：开发容器

入口：`make -C docker dev-up|dev-build|dev-test|dev-shell|dev-status|dev-down|dev-freeze`。

已核验：

- 双向挂载：宿主写入 `.sando_dev_mount_check`，容器追加后宿主可见，文件已删除。
- AMPL 探针：`ampl_gurobi_probe_ok x= 1.0`，Gurobi 13.0.2。
- `ROS_DOMAIN_ID=91`，与正式采集隔离。
- 编译锁：`/root/sando_ws/build-dev/.dev-build.lock`。

已完成（2026-09-08）：

- 第一次 `colcon` 完成；`dev_sando` SHA-256 `8b1717e2e09a38189c6a461d1c3ce73936d43d5d3a73982cc59d3bad451abc12`
- 增量：touch `test_instance_reservoir.cpp` 后重编约 32s；无改动约 8.5s
- `make -C docker dev-test` 13/13 通过（含真实 AMPL 适配器测试）
- CPU torch 装入 `docker/dev-workspace/python`（venv 需 `--system-site-packages`）
- `docker/dev-workspace/freeze/latest.json` 已写入
- 修复：两份脚本曾被截断污染，已从 HEAD 恢复并重打集合监督/采样补丁

## 阶段二：集合监督

实现：`scripts/integer_set_supervision.py`，训练方法 `set`。

- 损失：`logsumexp(有效分数) − logsumexp(好标签分数)`。
- 近优：`ε相对=0.01`，`J尺度=1`，`ε绝对=2e-6`。
- A/B 原样保留；C 为前 20 轮集合损失，完整表上再加期望代价。
- 快速专家记录用途 `expert_demo`；完整表用途 `complete_cost_table`。未求解候选为 `not_solved`。
- 几何多标签：`effective_polytope_mask` / `assignments_from_mask`。不同专家取完整赋值并集，不做逐段混合。反例 `(0,1,0,1,0)` 不在两个专家并集中。

宿主测试通过：`test_integer_set_loss.py`、`test_integer_expert_labels.py`、`test_integer_label_queue.py`、`test_integer_instance_sampler.py`、`test_integer_dagger_aggregate.py`、`test_baseline_sim.py`、`test_capture_campaign.py`。

8–16 条拟合和 A/B/C 同预算训练需要完整代价表和容器内 PyTorch。正式采集未完成，因此只准备了标记为 `development_small_batch` 的合成烟雾 `scripts/fit_integer_set_smoke.py`。

## 阶段三：吞吐

采集独占（只读，约 seed0–32 完成时）：

```
scenes=198
retained_instances=1980
flight_hours=4.56
instances_per_flight_hour=434.5
success_true=95
```

这是飞行墙钟，不是标注墙钟。435 是每飞行小时保留的规划实例，不是已验收标签。

森林诊断（只读，不改采集逻辑）：`static_forest` 场次一律 `observation timeout: goal_reached was not received`；多数已到目标附近（`goal_distance_m` 中位约 0.27m），少数未到。采集结束后再改判据。

标注队列：`scripts/integer_label_queue.py`。领取用原子改名；源文件指纹变化则拒绝。未对正式数据启动求解器，避免和正在飞的 AMPL 抢许可证。

采样：正式默认仍 10/5。开发协议 `uniform_plus_diverse_v1` 上限 20 已写进配置，容量校验放宽到 20，默认启动参数未改。

双容器物理采集：未做。正式串行采集仍占用 GPU，文档要求达不到筛选条件不得扩容。

## 阶段四 / 五

阻塞：aligned 训练集未完成，验证集 0，无完整候选表，无学生模型。

已具备但未跑真实闭环：`scripts/integer_dagger_aggregate.py`（固定验证集、按实例身份去重、拒绝非 train 分裂）。

因此没有第一候选可行率、回退率、900 场评测或学习收益数字。

## 失败与未做

- 宿主没有 PyTorch，集合损失的 torch 梯度测试在宿主跳过。
- 开发容器第一次编译时间长，报告提交时开发二进制可能仍未安装。
- 未中止正式采集，未把开发树挂进采集容器，未切换 Git 分支。
- 未声称吞吐已经提高。
