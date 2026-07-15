# PVRIG 双构象 Docking 资源与时间实测

- 统计日期：2026-07-15
- 计算节点：node23
- CPU：64 逻辑 CPU，32 物理核，2 threads/core
- HADDOCK3：2025.11.0
- 运行方式：本地 ext4 scratch 计算，完成后原子发布到共享 NFS
- 单个 job：1 个 VHH、1 个 PVRIG 构象、1 个随机 seed、4 CPU
- 正式单序列验证：2 个构象 x 3 seeds = 6 jobs

## 证据规模

- 成功 scratch jobs：652
- 其中候选 jobs：410
- 六个 jobs 全部完成的实体：105
- 六个 jobs 全部完成的候选序列：66
- 8 路生产阶段吞吐量：83.13 jobs/hour，即 13.86 条六-job序列/hour
- 终局 job 失败率：1/699 = 0.143%

## 单个 Docking job

候选任务实测：

| 指标 | P50 | P90 | P95 | 最大值 |
| --- | ---: | ---: | ---: | ---: |
| HADDOCK 主流程 | 4.87 min | 5.02 min | 5.05 min | 5.23 min |
| 包含发布和评分的总时间 | 5.03 min | 5.18 min | 5.23 min | 5.40 min |

全部控制和候选合并后，单 job 总时间 P50 为 5.04 min、P90 为 5.30 min、P95 为 6.20 min。完成本地计算、发布共享 run 后，native/cross 双参考评分的额外时间 P50 为 9.52 s。

单 job 固定请求 4 个逻辑 CPU。活动进程组 RSS 实测中位数约 849 MiB，范围约 727-917 MiB。共享 `runs/ + results/` 的30-job样本中位数为 22.35 MiB/job。

## 一条序列的正式六-job验证

66 条完整候选的实测结果：

| 指标 | P50 | P90 | P95 | 最大值 |
| --- | ---: | ---: | ---: | ---: |
| 六 jobs 同时运行的理论专用时长 | 5.11 min | 5.25 min | 5.29 min | 5.40 min |
| 当前共享8路队列中的实际首尾跨度 | 9.03 min | 10.20 min | 10.23 min | 11.27 min |
| 仅4 CPU串行运行六 jobs | 30.13 min | 30.88 min | 31.25 min | 31.71 min |
| CPU核时 | 1.94 core-hours | 1.99 core-hours | 2.02 core-hours | 2.04 core-hours |

正式验证若六 jobs 同时运行，需要：

- 24 个逻辑 CPU；
- 约 5.1 GiB 活动内存；
- 约 130-150 MiB 最终共享存储，建议按 200 MiB/序列预留以覆盖失败归档；
- 专用资源下约 5-6 min；
- 当前32-CPU预算的共享生产队列中约 9-11 min。

## 不同硬件规模下的预算

| 可用逻辑 CPU | 同时 jobs | 一条正式序列预计时间 | 说明 |
| ---: | ---: | ---: | --- |
| 4 | 1 | 约30-32 min | 六个 jobs 全串行 |
| 8 | 2 | 约16-18 min | 三轮 |
| 16 | 4 | 约10-12 min | 两轮，最后一轮2 jobs |
| 24 | 6 | 约5-6 min | 单条序列六 jobs 同时完成 |
| 32 | 8 | 实际约13.86条序列/hour | 当前 node23 生产配置 |

内存不是当前瓶颈。按约0.85 GiB/job估算，8 jobs 约需6.8 GiB；node23 实测仍有约113 GiB可用内存。HADDOCK3 是 CPU 工作负载，不需要 GPU。

## 可选的快速预筛

若只做临时预筛，可使用两个构象各一个 seed：

- 2 jobs；
- 8 个逻辑 CPU并行；
- 约1.7 GiB内存；
- 约5-6 min；
- 约0.65 core-hours。

但该模式不能替代正式结论，因为缺少 seed 重复性，不能判断是否达到每个构象至少2/3 seeds支持。

## 关键运行条件

必须在节点本地 scratch 中运行 CNS。相同任务直接在共享 NFS 中曾耗时约26 min，而本地 scratch 为4 min 47 s。共享 NFS只用于状态、锁和最终结果发布。

## 仅输入 VHH 氨基酸序列时的额外开销

当前流水线不要求候选自带三维结构。若已有一条 VHH 氨基酸序列，会先在 node1 上完成 NanoBodyBuilder2 单体建模，再进入 node23 的双构象 HADDOCK3 评价。PVRIG 的 8X6B/9E6Y 参考构象、界面约束和评分参考已经冻结，不需要为每条候选重新构建。

历史 1,024 条候选的 NanoBodyBuilder2 实测条件为：

- 6 条并行 GPU lane，分别使用 6 张 NVIDIA GeForce RTX 4090 24 GB；
- 每条 lane 同时只处理一个候选，每个候选配置 2 个 CPU threads；
- refined 建模失败时自动回退到 unrefined；
- `NBB2_START` 到 `NBB2_EXIT` 的计时已包含 PDB 链标准化、预测结构与输入序列一致性检查、主链几何 QC，以及向 HADDOCK 输入目录复制最终 PDB；
- 1,024/1,024 条均成功并通过上述序列和几何验证。

按每个候选最后一次成功记录统计：

| 指标 | P50 | P90 | P95 | P99 | 最大值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 序列到合格 VHH 单体 PDB | 17 s | 39 s | 57.85 s | 85 s | 226 s |

因此，在目标参考结构和 Docking 约束均已冻结的前提下，单条候选从氨基酸序列开始的端到端预算为：

| 配置 | 结构预测与 QC | 双构象六-job Docking | 端到端建议预算 |
| --- | ---: | ---: | ---: |
| 1 张 RTX 4090 + 专用 24 逻辑 CPU | 通常 17-58 s | 约 5-6 min | 约 6-7 min |
| 1 张 RTX 4090 + 当前共享 8-job 队列 | 通常 17-58 s | 约 9-11 min | 约 10-12 min |
| 1 张 RTX 4090 + 仅 4 逻辑 CPU | 通常 17-58 s | 约 30-32 min | 约 31-33 min |

结构预测与 Docking 不需要占用同一台机器：当前实践是 node1 用 GPU 生成 VHH 单体 PDB，node23 用 CPU 做 HADDOCK3。结构预测的 GPU 开销远小于后续六-job Docking 的 CPU核时，通常不是单条候选端到端延迟的主要瓶颈。上述 GPU计时是在 RTX 4090 24 GB 上测得；历史运行没有记录逐任务峰值显存，因此不能把 24 GB解释为 NanoBodyBuilder2 的最低显存要求。

## 解释边界

这里的“验证阻断”是验证 VHH pose 是否具有跨8X6B/9E6Y、跨seed、native/cross一致的 PVRIG-PVRL2 界面遮挡样几何。它不是实验功能阻断证明，也不是 Kd 或绝对亲和力预测。

Docking 部分的原始计时从已冻结的 VHH 单体 PDB 开始；上节已单独给出仅有氨基酸序列时的结构预测、结构质控和端到端总预算。
