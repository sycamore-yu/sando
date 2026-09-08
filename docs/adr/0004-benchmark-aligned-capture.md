---
status: accepted
---

# 采集按场景族分开，训练才随机起点

用户要求借鉴 YOPO 的自由空间起点采样，并把静态/动态场景靠向 SANDO 的 Simulation Benchmarking。Advisor 判定：正在进行的 `integer-racefix-serial-data` 固定起点未知动态重采不中断、不混入新协议。新协议 `benchmark_aligned_v1` 的主训练集仍是 Gazebo `empty_wo_ground`、点云-only 的未知动态；静态对照改为 `easy/medium/hard_forest` 世界，而不是空世界里 ratio=0 的程序障碍。RViz-only 且规划器订阅 `/trajs` 的已知动态只作单独特权表，不得进入主训练或与未知动态成绩合并。训练和验证用确定性盒子采样起点 `x∈[-1,3], y∈[-2,2], z∈[1.5,2.5]`、偏航保持 0；正式评测和论文对照保持 `(0,0,2)→(105,0,2)`。不采用 YOPO 的单帧深度倾倒、随机速度/加速度标签、图内划分或 ESDF 代价反传，因为那些会破坏规划实例监督。森林世界在多种子下是同一张地图，只能声称持有起点泛化，不能声称未见地图。
