# 联合时间–赋值网络执行计划（第一部分）

基点：`ce09ee3fc3330014b8247e954b41bd42ad856ba1`（2026-09-09 核对）。  
分支：`feat/ampl-gurobi`。工作树：仅宿主 `/home/tong/tongworkspace/dockerworkplace/sando`。  
ADR：本任务 0007，第二部分预留 0008。阶段 0–5 原文见 `docs/learning-stages-0-5.md`，本文件只声明继承，不改写历史报告。

## 冻结门槛

写入 `docker/dev-workspace/results/joint-time-v2/config.json`，运行前冻结：

| 键 | 值 |
| --- | --- |
| `n` | 5 |
| `learned_factor_range` | `[1.0, 2.5]` |
| `legacy_factor_range` | `[1.0, 5.0]` |
| `query_grid` | `[1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5]` |
| `off_grid` | `[1.37]` |
| `parity_atol` | `1e-10` |
| `residual_tolerance` | `2e-6` |
| `fd_scales` | `[1e-3, 1e-4, 1e-5]` |
| `fd_relative_error` | `1e-2` |
| `fd_near_zero_abs` | `1e-5` |
| `lambda_T` | `1.0` |
| `main_qp_per_request` | `1` |
| `main_assignment_per_request` | `1` |
| `main_time_per_request` | `1` |

## 本地身份（本轮核对）

- 开发容器 `sando-dev` 运行中，镜像 `sando-integer-centered:20260907`（`sha256:b5ceb87b1968…`），宿主源码挂到 `/root/sando_ws/src/sando`。
- 正式采集容器 `sando-integer-centered` 保持冻结哈希 `fd2c5e16…` / `75c50265…`，不挂宿主源码。对齐采集已结束（`integer-benchmark-aligned-capture.exit=0`）。
- 未跟踪文件与 `docs/fromchat/进度.md` 的本地修改均保留。
- 入口是 `make -C docker dev-status|dev-up|dev-build|dev-test|dev-freeze|dev-release`。仓库没有 `dest-*` 目标。

## 阶段、入口、门槛

| 阶段 | 入口 | 完成判据 | 状态 |
| --- | --- | --- | --- |
| 甲 单提议接线 | 时间 schema 2、候选上限 1、原回退 | 旧格式仍可读；1.37 段长/层时刻一致；失败路径有测试 | 格式与 QP 上限已通过容器测试。未做：2 静+2 未知动态小运行、10 条主提议轨迹、1000 组训练/在线对照 |
| 甲′ 12 请求小表 | `scripts/build_joint_time_small_table.py` | 六类×2；查询网格+1.37；同 `f` 复验；新 `f` 有缺失清单或真实重建 | 小表已写。同 `f` 12/12 参考。新 `f`（含 1.37）因缺 `visible_map` 阻塞 |
| 乙 共享条件双头 | 训练/在线同一 `h` 缓存 | 共享对象、优化器不重复、梯度归属、导出恢复 | 未开始 |
| 丙 时间梯度 | 解析例 + 预登记 30+30 | 两相邻尺度稳定；固定几何/动态局部分列 | 未开始 |
| 丁 监督训练 | 赋冻结→时间→条件赋值→共同 | 16 实例×100 小批后 3 seed | 未开始 |
| 戊 PPO 闭环 | 已有 SANDO 仿真 | 1000 转移 / 10 次更新 | 未开始 |

## 恢复命令

```bash
make -C docker dev-status
make -C docker dev-build
# 接线与时间格式
docker exec sando-dev bash -lc 'source /root/sando_ws/src/sando/docker/dev_env.sh && ctest --test-dir /root/sando_ws/build-dev/sando --output-on-failure -R "^(segment_time_consistency|timing_policy_inference|online_corridor_candidates)$"'
python3 tests/ampl_model/test_integer_timing_policy.py
python3 tests/ampl_model/test_reconstructable_request.py
```

旧实验 `docker/dev-workspace/results/learning-stages-v2/` 只读。新结果写 `docker/dev-workspace/results/joint-time-v2/`。
