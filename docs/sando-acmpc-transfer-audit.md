# AC-MPC 对 SANDO 联合时间与整数学习的可迁移性核对

日期：2026-09-07。研究目标来自当前讨论：RA-L、动态未知环境、实机，考虑联合学习时间与走廊赋值。本文只核对参考方法与推导可借鉴边界，不代表已完成实现或新颖性论证。

## 1. 版本与证据范围

- 主文献：[Actor-Critic Model Predictive Control，arXiv v8](https://arxiv.org/html/2306.09852v8)，2025-12-05，TRO 2025；另核对[作者提供的录用版 PDF](https://rpg.ifi.uzh.ch/docs/TRO25_ACMPC_Romero.pdf)。早期 arXiv v6 不是本次结论依据。
- 官方代码：[uzh-rpg/acmpc_public](https://github.com/uzh-rpg/acmpc_public)。本地读取 `/home/tong/tongworkspace/genesisworkspace/.refer/acmpc_public`，HEAD `c59e53aec11c1fffa8b69d99b0ee7879ba7ccb28`。
- 固定依赖：`mpc.pytorch` 指针 `63732fa85ab2a151045493c4e67653210ca3d7ff`；SB3 fork 指针 `152c353863d3b05fb5feed4deb37b952bb4beb7b`。本地依赖源码未展开；本次在线核对后者策略及通用 rollout 源码。未运行训练。

## 2. 原文的核心事实

AC-MPC 的网络输出时域二次成本参数 Q、p；MPC 首步控制解作为高斯策略均值。PPO 经该均值和可微求解器更新成本网络。训练时在求解结果后加探索噪声，部署直接执行均值。所用求解器只有输入约束，没有状态约束，碰撞惩罚不能变成硬避障保证。见 [§III-F、G 与 §VI](https://arxiv.org/html/2306.09852v8)。

实验观测包含机体状态和未来两个门的几何；每个任务重新训练。OOD 实验涉及外扰与机体参数改变；实机是 Circle/SplitS 竞速，使用运动捕捉。该结果没有建立在线发现、跟踪未知移动障碍的证据。见 [§IV-A、V-C/D/H](https://arxiv.org/html/2306.09852v8)。

## 3. 官方实现证据：实际输出与约束

| 检查项 | 源码核对结果 |
| --- | --- |
| 网络输出 | `mlp_mpc_policy.py:49–59` 输出 `28*T`；121–134 拆成 `14*T` 对角二次项及 `14*T` 线性项。前者通过正下界保持正；线性项按分量缩放、允许有符号项。 |
| 优化接口 | `mlp_mpc_policy.py:165–171` 将 `_Q,_p` 传入 MPC；186–204 返回首步总推力及三个机体系角速度，并归一化。没有输出时间分配或走廊整数。 |
| 梯度入口 | `mlp_mpc_policy.py:227` 设置 `distr_identity=True`，避免求解器之后再接可学习动作映射。缓存 `predictions` 在181行 detach，但用于均值的 `nom_u` 路径没有因此 detach。 |
| 输入约束 | `il_env.py:85–103` 只传 `u_lower/u_upper`；限总推力和三个角速度。没有状态界、障碍面或走廊约束参数。 |
| 固定时间 | `drone.py:167` 固定 `dt=0.02 s`，因此该参考实现没有验证通过可变时间求解器学习。 |
| 求解精度边界 | `mlp_mpc_policy.py:171` 显式 `lqr_iter_override=1`；`il_env.py:105–106` 不因未收敛退出或 detach。不能据此称每次前向都完成已收敛的全局最优求解。 |

对应作者代码：[策略](https://github.com/uzh-rpg/acmpc_public/blob/c59e53aec11c1fffa8b69d99b0ee7879ba7ccb28/training_modules/mlp_mpc_policy.py)、[求解封装](https://github.com/uzh-rpg/acmpc_public/blob/c59e53aec11c1fffa8b69d99b0ee7879ba7ccb28/diff_mpc_drones/il_env.py)、[动力学](https://github.com/uzh-rpg/acmpc_public/blob/c59e53aec11c1fffa8b69d99b0ee7879ba7ccb28/diff_mpc_drones/drone.py)。这些是本次读取版本的实现事实，不保证涵盖论文所有内部实验配置。

SB3 fork 的 `evaluate_actions` 使用新参数重新计算 MPC 均值，并评估已采样动作的 `log_prob`。这与“通过真实仿真器反传累计奖励”不同；环境回报和优势提供策略梯度信号，求解器只位于策略内部的可微路径。[固定版本 policies.py](https://github.com/uzh-rpg/stable-baselines3-acmpc/blob/152c353863d3b05fb5feed4deb37b952bb4beb7b/stable_baselines3/common/policies.py#L589)

对于探索约束，需要分三层：高斯原始样本可以越过有限输入界；该 fork 的通用 rollout 对 Box 动作裁剪后交环境，并保留原样本的 log probability；裁剪最多恢复同一输入盒，无法恢复整条预测轨迹的状态或避障性质。该通用调用路径存在，不等于已核实所有论文训练入口都采用它。[固定版本 on_policy_algorithm.py](https://github.com/uzh-rpg/stable-baselines3-acmpc/blob/152c353863d3b05fb5feed4deb37b952bb4beb7b/stable_baselines3/common/on_policy_algorithm.py#L150)

## 4. PPO 究竟如何穿过优化器

下面是根据上述接口写出的链式法则，属于解释性推导。令网络给出 `w_theta(s)=(Q,p)`，优化器首步解为 `mu_theta(s)=MPC(s,w_theta(s))`。对固定的采样动作 u 和固定方差，高斯策略有：

\[
\nabla_\theta\log\pi_\theta(u\mid s)
=\left(\frac{\partial w_\theta}{\partial\theta}\right)^\top
\left(\frac{\partial\mu}{\partial w}\right)^\top
\Sigma^{-1}(u-\mu).
\]

PPO 的概率比、裁剪和优势在其上产生损失系数；若方差可学习，还有方差项。这里的优化器导数是解对问题参数的敏感性。既没有穿过仿真器，也没有解决整数 argmax 的导数。MPC 内部使用动力学模型，不等于需要给真实环境或奖励函数求导。

## 5. 与 AllocNet 对照：联合 t、z 能继承什么

[AllocNet / Wu et al. 2023](https://arxiv.org/html/2309.15191v2)以连续分段时间作为网络输出，给定时间后求轨迹 QP，并利用隐式层训练；与 AC-MPC 的成本参数入口不同。它提供时间梯度设计参考，但没有替 SANDO 解决时空多面体赋值。

以下是本研究推断，而非三篇方法已经证明的结果：

| 要素 | 可借鉴 | 必须另行解决 |
| --- | --- | --- |
| 连续时间 t | AllocNet 的正时间参数化、固定时间 QP、求解后成本梯度 | 动态 STSFC 随 t 改变；走廊生成含离散步骤，不能只改变多项式时间矩阵却沿用旧安全时间标签。 |
| 整数 z | 学习输出组合、固定后求连续问题的分解思想 | 硬 z 没有普通路径梯度；采用代价加权监督、枚举期望、策略梯度或明确标注偏差的松弛。 |
| 闭环任务信号 | AC-MPC 的长期优势、策略内求解器和动力学随机化 | 需要规划步动作语义、求解失败处理、动态感知状态、真实计算延迟；不能照搬总推力动作头。 |
| 硬避障 | 保留 SANDO 实际多面体约束及检查 | AC-MPC 本身没有该保证；联合时间学习必须维护时间层、执行时刻、障碍上界和跟踪误差的一致性。 |
| 探索 | 在仿真中验证探索强度与分布外稳定性 | 在 QP 解后给轨迹/控制加噪不能保留轨迹硬约束。更适合在求解之前探索 t,z，再对最终候选严格求解与验收。 |

“联合学习”不要求两个互不依赖的头同时输出。一个更符合动态几何依赖的候选结构是：

\[
t\sim p_\theta(t\mid s),\qquad
\mathcal C=\operatorname{STSFC}(s,t),\qquad
z\sim p_\theta(z\mid s,t,\mathcal C),\qquad
x^*=\operatorname{QP}(s,t,z,\mathcal C).
\]

时间改变会改变走廊的几何与可行整数集合，故训练与推理应记录完整条件。这里的 t 可以先限定为统一分段时间缩放，再独立研究各段非均匀时间；后一种方案还改变 SANDO 原来的时间层定义。

## 6. 两种训练设计不要混称

**设计 A：规划动作 PPO + 可微辅助损失。** 在求解之前采样 t,z，记录 `log p_theta(t,z|s)`，把严格 QP、轨迹跟踪和仿真视为环境。这一 PPO 更新不需要 QP 梯度；另加可微轨迹成本，用固定 z 下的时间敏感性训练连续头。优点是所有执行候选仍需过 QP。需明确辅助项与长期回报是两个目标，分别消融；对不光滑的走廊生成，冻结走廊所得只能称条件梯度或局部代理，部署仍按新时间重新构造/检查。

**设计 B：AC-MPC 风格执行动作密度。** 令求解后执行量成为分布参数，用动作概率的导数穿过 QP 训练时间头。这更接近 AC-MPC，却需要推导合法的执行动作分布，并处理求解后探索与硬轨迹约束的冲突；整数头仍需额外梯度估计。不能同时声称“所有执行动作都是原 QP 可行解”又无条件地在解后添加高斯噪声。

两者都可以联合学习 t,z，但梯度目标与安全性质不同。若目前目标是形成清晰的 RA-L 主线，设计 A 更容易逐项验证；“更容易”是研究判断，需要通过实验决定收益，不是结论。

## 7. 不能从 AC-MPC 继承的论文主张

- 成本网络有 OOD 优势，不能推出走廊整数策略对未见动态障碍数量、速度、遮挡模式具有相同优势。
- 门竞速实机结果，不能替代未知障碍检测、追踪误差、遮挡突现和安全走廊时效性的实验。
- 输入约束的满足，不能推出 SANDO 所需的连续时间避障、跟踪裕度或递归可行。
- 短期 MPC 预测辅助 critic，不能直接当作未知障碍的真实未来；若尝试 MPVE，预测模型误差与真实闭环回报需要单独检查。

本轮没有检查用户拟采用的 L2O-MIQP 具体版本和梯度实现；该部分应与对应核对文档合并后再确定三者的组合方式。也没有实施训练、修改求解器或测试实机。
