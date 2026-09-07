# AMPL / AMPLS 后端

本地基准：`93b2eed6bb7e300d212372fe20fc8231508162e0`。实现保留原始 SANDO 轨迹公式、并行时间搜索和 `GRB_OPTIMAL` 成功判定。原始方案见 `im.md`；本文件记录实际实现。

## 构建与运行

```bash
make build BUILD_JOBS=4
make preflight BUILD_JOBS=4
make run-demo SCENARIO=static_easy
```

运行中的 AMPL 容器默认使用固定名称 `sando-ampl-session`，因此同一宿主机上一次只启动一个会话。开始交互运行前先停止演示会话，再执行一行命令：

```bash
make stop
make run-interactive
```

运行目标不会自动停止或替换已有容器；如果出现名称冲突，说明已有会话仍在运行，请先执行 `make stop`。`make stop` 只停止 `CONTAINER_NAME` 指定的容器。需要并行运行时，可为每个会话设置不同的 `CONTAINER_NAME`，并自行配置不冲突的 ROS 域和 Gazebo 端口。

授权 UUID 默认从宿主机 `~/.config/ampl/uuid` 读取，可通过 `AMPL_UUID_FILE` 覆盖。文件应为 0600 权限，父目录 0700；运行时只读挂载，不进入镜像。结果目录默认 `docker/results`，可用 `RESULTS_DIR` 覆盖。无 DISPLAY 时入口启动 Xvfb。Makefile 默认 `ROS_DOMAIN_ID=42`，可覆盖；这是为避免当前宿主机已有域 20 仿真互相发现。Gazebo 默认 `GAZEBO_MASTER_URI=http://127.0.0.1:11346`，避免宿主机已占用的 11345 端口，也可覆盖。原场景脚本通过既有 `--ros-domain-id` 参数使用该值。

## 实现边界

- `SANDO_USE_AMPL=ON` 编译记录式 C++ 适配层；关闭时保留原生 Gurobi 后端。
- 每次优化导出完整、真实的 AMPL 模型，使用 AMPL 编译器生成 NL，经 AMPLS 导入并从原生变量名称恢复结果。
- `SANDO_AMPL_MODE=full` 每次重新导入；Makefile 默认 `persistent` 首次导入后保留 AMPLS 所有者，通过官方 Gurobi C 接口重建约束和更新变量、目标。每次仍编译完整 AMPL 模型以维持授权与核验路径；当前没有常驻 AMPL 解释器，因此不能宣称消除了编译开销。
- `SANDO_AMPL_VERIFY_UPDATES=1` 对持久化更新另做独立完整导入，核对终态、目标和双方解的约束可行性。参考求解超时等非终态记录为核验未完成。
- `SANDO_AMPL_TRACE=1` 输出导出、编译、准备、求解、读取及适配层墙钟毫秒数（不含独立核验和原始表达式生成）；原始 `Runtime` 口径保持 Gurobi 内部秒数乘 1000。
- `SANDO_AMPL_AUDIT_DIR` 保存每次的 `.mod/.nl/.col/.row` 和原生 LP；默认不保留临时模型。
- 目标值按记录的原始表达式在返回解上以 long double 累加计算；原生 `ObjVal` 保留于 TRACE。N6/L2 测试发现原生报告比实际返回轨迹代价高约 8e-5，而记录表达式与轨迹代价一致到 3e-11，因此使用原始目标值做 postsolve 映射，未改变求解器状态或容差。
- AMPL 可能省略无用或固定变量，适配层恢复这些变量的原始域；有引用且非固定的变量若无法映射则报错。

## 冷启动并发故障排查

2026-09-07 的无运动故障包含两个问题：重复启动的容器共用 ROS 域和 Gazebo 端口；单独启动时，规划器仍可能在 AMPLS 并发导入模型时崩溃。核心转储显示一个线程在 `AMPLSOpen_gurobi/getCB`，另一个线程正在 `AMPLSLoadNLModel`。旧测试先单独求解再做并发测试，掩盖了首次加载的竞态；新增九实例同步冷启动测试在修复前第二次启动时以 139 退出。

修复用进程级互斥锁保护完整导入和 AMPLS 所有者销毁，包括独立核验模型。模型编译、原生更新和 `GRBoptimize` 位于锁外。修复后 30 次全新进程冷启动通过；进一步跳过适配层的两次求解前回调，用原生求解回调验证两个求解确实重叠，该测试再连续通过 30 次。五项回归测试和持久化加独立核验的轨迹矩阵通过。

本机镜像已从未激活授权的原应用镜像增量编译更新，没有提交运行中的容器。使用 `DISPLAY=:10.0 make run-demo SCENARIO=static_easy` 正常启动，无调试器、无手动重发目标，观测到单一里程计发布者、8 秒内约 25.32 米位移，随后进入 `GOAL_REACHED`，最终位置约 `(104.83,-0.09,1.91)`。新机器按本文正常构建流程即可包含修复。

`make preflight` 现在同时运行独立 AMPLS 接口探针、五项生产适配层测试，以及 20 次全新进程冷启动测试。

## 锁定依赖

AMPLS 源码提交 `9ceda9a9b32d6cc3c4428210c3824fa93b0dc0e1`，`amplpy==0.18.0`、`ampl_module_base==20260809`、`ampl_module_gurobi==20260624`。配套 native Gurobi 实测为 13.0.2；原镜像为 11.0.3，耗时不能作为同版本严格比较。官方库包及 SHA-256 在 `scripts/install_ampls.sh` 固定。镜像内 `/opt/sando-source.commit` 与 `/opt/sando-source.sha256` 记录本地构建来源。

## 验证状态

接口探针已实测覆盖真实指示约束模型、九并发实例、重复求解、超时、中止与恢复。表达式单元测试及完整导入、持久化更新探针已通过。开发容器整包构建通过，完整导入和默认持久化两种模式的 `static_easy` 均完成飞行并进入 `GOAL_REACHED`，观测位置 `(104.88,-0.22,1.87)`，目标 `(105,0,2)`。七分钟内八轮重复求解通过；最新构建的同一个持久模型保持 360 秒后更新并独立核验也通过（05:07:05–05:13:05 UTC）。L2 目标值报告差异已通过原始目标的 postsolve 映射处理；完整导入测试 4/4 通过，持久化加独立核验的 18 种轨迹组合及空走廊拒绝均通过，保持原始 2e-5 校验容差。依赖镜像 `sando-ampl-dependencies` 已构建完成（manifest list `sha256:d4b599232092e1a333f0d2e4bb662b559985a935ec794a81e8e017ac8f30c8cb`）。最终 `sando-ampl` 镜像及 make 演示入口已完成本机验收，冷启动修复的最新结果见上节。

轨迹矩阵实测：首次导入的适配层中位耗时 59.37ms，更新为 52.75ms；其中 AMPL 编译约 38–39ms，导入准备 11.83ms、更新准备 1.12ms。此小规模样本不包含参考求解核验，不代表整场景实时性或与原生版本的严格比较。

## 依赖镜像完成后的下一步

在本地仓库根目录或 `docker` 目录运行 `make build BUILD_JOBS=4`，复用依赖缓存构建最终应用层。随后运行 `make preflight BUILD_JOBS=4`，最后运行 `make run-demo SCENARIO=static_easy`，观察规划器进入 `GOAL_REACHED`。

需要复现全部适配层测试时，最终镜像生成后在仓库根目录运行：

```bash
docker run --rm \
  --mount type=bind,src="$HOME/.config/ampl/uuid",dst=/run/secrets/ampl_uuid,readonly \
  sando-ampl bash -lc 'source /root/sando_ws/install/setup.bash && ctest --test-dir /root/sando_ws/build/sando --output-on-failure'

docker run --rm \
  --mount type=bind,src="$HOME/.config/ampl/uuid",dst=/run/secrets/ampl_uuid,readonly \
  -e SANDO_AMPL_MODE=persistent -e SANDO_AMPL_VERIFY_UPDATES=1 \
  sando-ampl bash -lc 'source /root/sando_ws/install/setup.bash && ctest --test-dir /root/sando_ws/build/sando -R ampl_trajectory_formulas --output-on-failure'
```

实现过程和问题处理见 [改造报告](ampl-implementation.md)。
