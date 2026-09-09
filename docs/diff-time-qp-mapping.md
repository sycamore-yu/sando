# Diff-time-QP mapping（Phase B）

目的：把真实 SANDO fixed-Z continuous QP 与 `prototypes/time_fixed_z_qp` 的 Python 复现逐项对齐，作为 Phase C true Diff-QP 的唯一规格。  
原则：复现真实 SANDO，不另造“类似”问题。

工程基线：`103faa1`。FD 训练只作 oracle / ablation，不算最终可微层。

---

## 1. 时间尺度

| SANDO C++ | 数学 | Python (`run_time_qp.py`) | Diff 实现备注 |
| --- | --- | --- | --- |
| `sando_time::segmentDuration(initial_dt, dc, f)` | \(d=\max(d_0^{\text{raw}},2d_c)\,f\), \(d_0=\max(d_0^{\text{raw}},2d_c)\) | `segment_dt(initial_dt, dc, factor)` | 对 `f` 线性；矩阵对 `f` 多项式依赖 |
| `horizonDuration(N,…)` | \(T=N\,d\) | `T = N * duration` | 一致 |
| `SolverGurobi::setInitialDt` + factor | 各段 `dt_[i]=d`（等时长） | 同左 | fixed-Z 等时长假设保持 |

权威：`include/sando/segment_time.hpp`。

---

## 2. 多项式与基

| SANDO C++ | 数学 | Python | Diff 备注 |
| --- | --- | --- | --- |
| 每段三次多项式，系数 \(a,b,c,d\)（轴独立） | \(p(t)=at^3+bt^2+ct+d\)，局部 \(t\in[0,d]\) | 决策变量按轴×段×4 展平，`D=12N` | 与 Gurobi 变量布局需用 PlanningInstance 校验 |
| Bezier / Minvo 控制点（`BasisConverter`, `M_be2mv_`） | 位置 CP 用于走廊 / 动力学 L∞ | Python 用多项式在 \(0,d/3,2d/3,d\) 等节点的求值行代替 CP | **已知近似点**：C++ 正式路径用 Minvo/Bezier CP；Python 用节点采样行。Phase C 须对齐到与 Gurobi 同一 CP 定义，或证明节点行与 L∞ CP 在本参数下数值等价 |
| `getVelCP` / `getAccelCP` / `getJerkCP` | 对 \(d\) 依赖的 CP 线性式 | `vel`/`acc`/`jerk` 基行随 `t=d` 重建 | 必须随 `f` 重算，禁止 stale 基 |

---

## 3. 边界与连续性

| SANDO C++ | 数学 | Python | Diff 备注 |
| --- | --- | --- | --- |
| `setX0` / `setXf` | 段 0 起点 / 段 N−1 终点的 pos/vel/acc | `derivative_bases` 起终点等式 | 一致 |
| 段间 C² 连续 | 段 \(n\) 终点 = 段 \(n+1\) 起点（pos/vel/acc） | 相邻段起终点基差 = 0 | 一致 |

---

## 4. 地图与动力学界

| SANDO C++ | 数学 | Python | Diff 备注 |
| --- | --- | --- | --- |
| Map bounds on position CPs | \(x_{\min}\le x\le x_{\max}\)（各轴） | `map_lower`/`map_upper` 对位置行 | 一致 |
| L∞ vel/acc/jerk（`dynamic_constraint_type=Linf`） | \(\|v\|_\infty\le v_{\max}\) 等 | 逐轴 ±limit | 参数须来自 PlanningInstance / Parameters，禁止硬编码偏离正式场景 |
| 当前 prototype `limits` | — | 常写死 `v=5,a=20,j=100` | **审计缺口**：Phase C 前改为从 instance/runtime 读取 |

---

## 5. 走廊与固定 Z

| SANDO C++ | 数学 | Python | Diff 备注 |
| --- | --- | --- | --- |
| `setPolytopes` / `TimeLayered` | 每段候选多面体 \(A_p x\le b_p\) | `corridors[t][p]` planes `[nx,ny,nz,ub]` | 平面约定一致 |
| 指标 / atleast-one（MIQP） | 二进制选 poly | fixed-Z：只保留 assignment 指定 poly，无 binary | 训练与部署 fixed-Z 路径一致 |
| Big-M 松弛（若用） | — | `records` 中 `big_m` 供未固定指标路径 | fixed-Z hard QP 应直接 \(A_{Z_t} x\le b_{Z_t}\)，无 Big-M |

Endpoint snap（已落地）：decomp 种子 `path.front/back =` 连续 start/goal，保证 X0/Xf 可落入走廊。

---

## 6. 目标与轨迹恢复

| SANDO C++ | 数学 | Python | Diff 备注 |
| --- | --- | --- | --- |
| `jerk_smooth_weight * Σ ‖u‖²` | \(J=w\sum\|jerk\|^2\) | `weight * ‖R x‖²`（+ ridge） | 权值须与 instance `jerk_smooth_weight` 对齐 |
| `getPieceWisePol` / coefficients | 三次系数 → 轨迹 | `recover` / `C @ x` 控制点 | 前向与 Gurobi 已有 `time_fixed_z_forward_probe` 证据 |

---

## 7. 对 `f` 的可微依赖（Phase C 规格）

正式路径要求：

\[
f_\theta=\mathrm{NN}(x)\;\xrightarrow{\;}\; d(f)\;\xrightarrow{\;}\; (P(f),q(f),A(f),b(f),G(f),h(f))\;\xrightarrow{\mathrm{QP}}\; x^\*(f)\;\xrightarrow{\;}\; B^\*(f),\,J(f)
\]

且 `loss.backward()` 穿过 QP（CVXPYLayers DPP 或 KKT implicit）。

禁止：`.detach()` / `.item()` / `float(tensor)` / `numpy()` 后重建 QP 再声称梯度穿过优化器。

当前 FD：

\[
\frac{J(f+\varepsilon)-J(f-\varepsilon)}{2\varepsilon}
\]

仅作 oracle / validation / ablation。

---

## 8. Phase C 实施优先级（锁定）

1. ~~CVXPYLayers + 全矩阵 Parameter~~：**已否证** — 对 `f→矩阵→CvxpyLayer` 测得 jerk 梯度相对误差 ~6%、`v·x*` ~79%（同层 FD 稳定）。证据：`prototypes/time_fixed_z_qp/evidence/diff_time_qp_probe0.json`。  
2. **采用：active-set KKT implicit differentiation**（`diff_time_qp_kkt.py`）：前向 Clarabel hard QP；反向解活跃 KKT。jerk / solution probe 相对 FD ~1e-7。pack16：**15/16** 双探针通过（失败保留）。  
3. 禁止为 DPP 改写硬约束语义。

---

## 9. 开放缺口

- [x] limits/weight：与 `config/sando.yaml` 默认对齐（pack 未存字段）  
- [x] fixed-Z：硬约束直接写入，无 Big-M  
- [ ] Python 节点采样 vs C++ Minvo CP：仍待比特级/数值审计  
- [x] 选 KKT implicit（CvxpyLayer 全矩阵路径否证）  

---

## 10. 复现命令（映射审计）

```bash
# C++ forward vs frozen translated trajectory
# (install-dev) time_fixed_z_forward_probe <fixture> <expected_obj>

# KKT true Diff-QP vs FD oracle
cd prototypes/time_fixed_z_qp
python diff_time_qp_kkt.py --index 0
```

证据目录：`prototypes/time_fixed_z_qp/evidence/`。
