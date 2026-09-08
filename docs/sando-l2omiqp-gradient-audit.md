# L2O-MIQP 梯度、不可行性与公开实现核查

核查日期：2026-09-07。假设读者理解 MIQP/QP 和反向传播，但不假设熟悉 STE 或可微优化实现。

**结论：L2O-MIQP 确实让连续优化反馈训练整数预测器，办法是“硬整数前向 + STE 替代反向 + 带松弛变量的可微 QP”。这不等于原始硬离散映射有普通导数。** 此外，作者当前公开代码的两个实验分支不一致：机器人导航分支保留 QP 梯度链，能量系统分支把预测值 `detach` 后传入 QP，切断该链。复现时必须区分论文方法与此实现版本。

## 核查对象与证据版本

- 论文：Viet-Anh Le、Mu Xie、Rahul Mangharam，*A Hybrid Learning-to-Optimize Framework for Mixed-Integer Quadratic Programming*。[arXiv 记录](https://arxiv.org/abs/2511.19383)显示最新为 **v2，2026-05-13**，备注为 final L4DC 2026；v1 为 2025-11-24。本文以 [v2 正文](https://arxiv.org/html/2511.19383v2) 为准，未把备注当作独立出版社出版证明。
- 代码：[mlab-upenn/L2O-MIQP](https://github.com/mlab-upenn/L2O-MIQP)，读取时 HEAD 为 **`e7da6932a9ac6fa218c0f7f1d5fada1243c5944b`**，提交日期 2026-04-15。代码早于 v2；不能未经验证假定它完整复现 v2。
- 已读取网络、两个实验的 QP 构造和训练/评估调用链。以下代码引用均固定到该提交。未安装依赖、未运行训练；当前 `python` 缺少 `torch`。因此实现问题为静态数据流核查结果，不声明已经重现论文指标。

## 论文机制及保证范围

Remark 1 明确使用 STE。式 (10) 对连续约束引入非负松弛并加线性罚项；式 (12)–(14) 对 KKT 系统求导。式 (16) 混合目标值、约束违反和专家整数监督；纯整数约束另在损失中处理。Assumption 1 要求严格凸 QP。Theorem 2：固定整数的原 QP 可行，且罚权重大于最优对偶乘子无穷范数时，松弛解与原解一致。Theorem 3 在正定 Hessian 或紧致定义域等条件下，声明足够大罚权重得到最小违反量，再最小化原目标。上述结论均不保证网络总能预测可行整数，也不保证 STE 为真实梯度或训练达到全局最优。见 [v2 §2.2–3.2、Appendix A](https://arxiv.org/html/2511.19383v2)。

Theorem 3 的使用还应核对具体问题的线性约束误差界与有界区域；附录用了 Hoffman 误差界和目标的 Lipschitz 界。无界域上的二次函数并不全局 Lipschitz，应用时需明确相关有界集合，不能直接把某个固定罚权重宣称为通用证书。这是对证明应用条件的审慎解读，本文未独立完成该定理的一般性证明或反例检验。

## 机器人导航分支：梯度链确实连接

[`src/neural_net.py:6–13`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/src/neural_net.py#L6) 中 `STE_Round.forward` 返回取整值，`backward` 原样返回上游梯度。`MLPWithSTE.forward` 先 sigmoid，再调用该算子（77–85 行）。因此：

\[
a=h_\omega(s),\quad p=\sigma(a),\quad z=\operatorname{round}(p)
\]

前向 \(z\in\{0,1\}\)，反向人为设定 \(\widehat{\partial z/\partial p}=I\)。这是一种替代梯度；数学上的 round 对输入几乎处处导数为零，在阈值处不连续。

[`robot_nav/miqp.py:23–48`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/robot_nav/miqp.py#L23) 将 `y_pred` 经过 reshape、`.cpu()` 传入 `CvxpyLayer`，**没有 `detach`**。CPU/GPU 拷贝本身不等于断开自动求导。QP 内预测位是连续参数 `obs_binary_param`，在避障约束右端通过 big-M 仿射进入；即使取值是 0 或 1，层的导数仍针对其连续参数扩展定义。见 [参数与约束构造](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/robot_nav/miqp.py#L227)。

据此，完整的反向传播可写成下式；这是依据代码推导的链式关系，帽号强调 STE：

\[
\widehat{\nabla_\omega L}
=\left[L_z+L_x\frac{\partial x_\rho^*}{\partial z}
+L_\epsilon\frac{\partial\epsilon_\rho^*}{\partial z}\right]
\widehat{\frac{\partial z}{\partial p}}
\frac{\partial p}{\partial a}\frac{\partial a}{\partial\omega}.
\]

这里 \(x_\rho^*,\epsilon_\rho^*\) 是松弛 QP 的解；连续层求导与离散算子的替代反向是两个不同环节。不能把连续层导数的准确性扩展成整个硬整数策略梯度的准确性。

[`robot_nav/miqp.py:50–63`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/robot_nav/miqp.py#L50) 分别计算目标、Huber 专家监督、松弛量及约束违反；[`src/trainer.py:156–214`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/src/trainer.py#L156) 加权后执行 `loss.backward()`。这意味着该实现支持优化反馈，不局限于模仿专家标签。

## 不可行时到底求解什么

机器人导航代码只对避障/机器人间约束加松弛，QP 内罚权重设为 \(10^4\)；初始状态、动力学、位置/速度/控制边界仍是硬约束。见 [`robot_nav/miqp.py:246–343`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/robot_nav/miqp.py#L246)。因此“松弛 QP 总有解”在该代码里仍以未松弛约束可行为前提；异常初态等情况并不由避障松弛修复。

优化器可以返回非零避障松弛。它精确求解的是带罚项的问题，不能称为已严格满足原始避障约束的轨迹。代码没有计算每个实例的最优对偶界来证明固定 \(10^4\) 满足 Theorem 2。定义了 `eps_ridge`，但目标中的 ridge 项被注释；不能仅因变量名存在就声称已添加全空间正定正则。原动力学约束下是否在独立自由变量上严格凸，应分析约化 Hessian。

## 训练与推理：同一松弛前向，并非部署时自动硬化

机器人训练入口实例化 `MLPWithSTE`（[`robot_nav/train.py:143`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/robot_nav/train.py#L143)）；评估入口同样如此。公共评估函数设置 `.eval()` 与 `torch.no_grad()`，但仍调用同一个 `solve_miqp`（[`src/trainer.py:316–347`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/src/trainer.py#L316)）。

因此已核查的评估路径是硬整数 + 松弛 QP；训练时额外启用替代反向。未看到这里根据非零松弛自动切换硬 QP、拒绝轨迹或启动原 MIQP 的逻辑。论文 §4 对求解时间也明确包括松弛 QP。若移植到 SANDO 时增加硬约束接受检查与回退，那是需要显式实现和评估的部署逻辑。

## 能量系统分支：两处必须区分的实现事实

**第一，前向使用 hard Gumbel-Softmax，但 QP 反馈被断开。** [`energy/train.py:84–91`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/energy/train.py#L84) 使用 `MLPWithSoftmaxSTE`，候选为 0、1、2、3；默认 `hard=True,use_gumbel=True,tau=2.0`。见 [`src/neural_net.py:93–117,152–176`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/src/neural_net.py#L93)。这与机器人分支的逐位 sigmoid-round 不同。

然而 [`energy/miqp.py:134–138`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/energy/miqp.py#L134) 对 `y_pred` 使用 `detach().cpu()`。据静态计算图，这使 QP 返回的连续轨迹和松弛对网络参数无梯度。仍可回传的是显式依赖 `y_pred` 的整数成本、整数约束违反和监督项；见 [目标和损失](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/energy/miqp.py#L150)。**“整个模型可以 backward”不足以证明“QP 分支实际在训练网络”。** 未据此推断作者发表实验使用的代码也必然存在该断链。

**第二，评估默认仍有 Gumbel 采样。** [`energy/evaluate.py:89`](https://github.com/mlab-upenn/L2O-MIQP/blob/e7da6932a9ac6fa218c0f7f1d5fada1243c5944b/energy/evaluate.py#L89) 使用相同默认构造；网络 forward 没有依据 `self.training` 关闭 Gumbel。所以 `.eval()` 不使该分支自动确定化，同输入多次评估可能输出不同整数。

另一个未被默认入口使用的分支也需注意：`use_gumbel=False,hard=True` 时，170 行的 `hard_one_hot - hard_one_hot.detach() + soft` 在前向抵消成 `soft`，并不产生宣称的硬 one-hot。这是静态代数结果，不影响默认 Gumbel 路径的结论，但不能直接把该选项当作可靠的确定性硬推理实现。

## 如何修正前一轮解释，并用于 SANDO

应将“固定硬整数会阻断梯度”完整表述为：**普通硬选择没有可用于标准反向传播的真实路径梯度；L2O-MIQP 通过显式指定 STE 替代反向，使硬整数前向仍可以利用连续 QP 的优化反馈训练。** 这两句话相容；前一轮若被理解成这种架构不能训练，就是不完整的解释。

针对 SANDO 的实现含义如下，属于本次代码核查后的推导：

1. 若直接按整数索引删除未选走廊，再调用外部 QP，索引操作本身不会提供论文所需的连续参数敏感度。需要定义明确的参数化连续扩展，例如保留全部候选约束，用整数参数仿射激活；并检查 big-M 尺度对替代梯度的影响。
2. 下层训练 QP 的松弛只为产生学习信号，不能直接等同于原 SANDO 的安全约束证书。若部署只接受硬可行轨迹，必须记录接受条件与失败处理，并将其延迟纳入比较。
3. SANDO 的纯整数“至少选一条”约束、走廊标签多解，以及三次多项式目标在可行自由度上的严格凸性，都需要独立核查。不能把机器人示例的位输出和罚权重机械复制。
4. 最小复现验收应逐项检查：硬前向的取值、对 QP 参数的小扰动敏感度、每个损失项对网络参数是否有梯度、非零松弛实例的处理。对整体 STE 网络做有限差分不会得到相同梯度，这是替代估计的定义所致；连续 QP 层应单独验证。

这篇工作应作为当前改造的直接方法基线。把相同 STE、松弛 QP 和混合损失搬到 SANDO 是复现/适配工作；论文新增贡献仍需用明确假设及消融实验建立。
