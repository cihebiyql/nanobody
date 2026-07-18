# PVRIG V6 Target-Conditioned Docking-Geometry Surrogate

日期：2026-07-17

## 目标

建立一条可在 Node1 四块 RTX 4090 上自动运行、可断点续训、可审计的训练流程：

```text
VHH sequence + label-free monomer structure
+ fixed PVRIG 8X6B/9E6Y target context
-> predict independent dual-receptor computational Docking geometry
```

冻结主目标为 `R_dual_min`。输出不是结合概率、Kd、实验竞争阻断、实验 blocker truth 或 Docking Gold。

## 当前监督数据

| source | candidates | parent clusters | teacher reliability |
|---|---:|---:|---:|
| V4-D OPEN_TRAIN | 226 | 20 | multi-seed, weight 1.0 |
| V4-H Stage1 terminal | 1281 | 11 | dual receptor, single seed 917, weight 0.65 |
| 合计 | 1507 | 31 | candidate-level supervision |

V4-H 的 39 条 `TECHNICAL_INCOMPLETE` 只能进入无监督/一致性输入，不能作为负样本。V4-H Stage2/Stage3 只用于更新同一 candidate 的测量方差和 teacher weight，不扩展为独立训练行。

## 数据边界

- 所有 split 以 `parent_framework_cluster` 为单位；
- OPEN_DEVELOPMENT32 不参与模型或超参数选择，只在配置冻结后检查；
- V4-F/test32 保持 sealed；
- legacy128 不合并；
- partial937 不再进入主训练或模型选择；
- candidate ID、parent ID、batch ID、campaign ID 不作为模型输入；
- campaign 只控制 sample weight 和审计，不作为可学习特征。

## 模型

```text
VHH residue PLM (ESM-C 600M / ESM2-650M / ESM2-3B)
  + IMGT/CDR position features
  + 126 label-free monomer structure descriptors
  + fixed 8X6B/9E6Y target/hotspot context
  -> target-conditioned cross attention/contact bottleneck
  -> M2 structure baseline + bounded neural residual
  -> R8, R9, R_dual_min, log variance, optional contact/ranking heads
```

M2 residual branch用于保护当前已验证的结构信号。ESM2-3B 仅在 600M/650M smoke 和基础 lane 通过后启用 LoRA/gradient-checkpointing 或两卡 FSDP。

## 四卡实验矩阵

1. GPU1: ESM-C 600M frozen + M2 residual；
2. GPU2: ESM-C 600M LoRA + dual-regression heads；
3. GPU3: ESM2-650M LoRA + contact bottleneck；
4. GPU4: ESM2-650M + residue/structure fusion；

第一阶段完成后，最佳两个配置各运行两个 seed。ESM2-3B 容量实验在第二阶段使用 GPU3-4，不能修改 split、目标或晋级指标。

## 损失

```text
1.00 weighted Huber(R_dual_min)
0.35 Huber(R_8X6B)
0.35 Huber(R_9E6Y)
0.25 soft contact loss（contact teacher可用时）
0.10 within-parent ranking
0.10 Top20 auxiliary
0.10 heteroscedastic NLL
0.10 M2 residual regularization
```

执行时逐项 ablation，不允许把所有可选头混成一个无法归因的单次结果。

## 评估和停止条件

- deterministic 5-fold nested whole-parent OOF；
- 在相同 fold 上重新计算 M2，而不是沿用 226 数据的绝对分数；
- 主指标：global Spearman；
- 保护指标：parent-centered Spearman、macro-parent Spearman、MAE、Top20 recall；
- parent bootstrap 比较 V6 与同数据 M2；
- target/hotspot shuffle、sequence-only、structure-only 为必须的 antigen-blindness controls；
- OOM 自动减 batch 并增加 accumulation；连续两次 NaN 停止该 lane；
- `/data1` 可用空间低于 180GB 禁止新 checkpoint，低于 150GB 安全停止；
- 只保留 best 和 last checkpoint。

## 自动执行链

```text
source hash preflight
-> data materialization
-> synthetic CPU tests
-> single-GPU 50-step smoke
-> four-lane GPU smoke
-> phase-A training
-> automatic metric gate
-> top-two multi-seed promotion
-> optional 3B capacity lane
-> ensemble + score 1320/720 pools
-> active-learning acquisition package
```

