# PVRIG V4-D 结构增强代理模型执行记录（2026-07-17）

## 1. 目标与证据边界

本轮目标是验证：

```text
冻结 VHH 单体结构
是否能提高 sequence surrogate 对独立 8X6B/9E6Y Docking 连续几何的逼近能力
```

冻结主目标仍是 `R_dual_min`。所有结果仅表示：

> post-hoc development-only computational docking geometry evidence

不表示 Docking Gold、PVRIG 结合概率、Kd、竞争阻断实验或最终提交依据。V4-F prospective test32 本轮保持零标签访问、零预测输出；legacy128 未合并；V4-D formal evaluator 的原始 `FAIL` 状态未被改写。

## 2. 已完成的数据交付

### 2.1 V1.2 open258 teacher

Node23 上只执行了一次冻结构建，终态：

```text
DEV1_V1_2_RELEASE_READY_TEST32_SEALED
```

交付结果：

| 项目 | 数值 |
|---|---:|
| 原始成功 Docking jobs | 1,547 |
| 完整 pose pairs（过滤前） | 14,490 |
| 因 native overlay RMSD > 1 Å 删除的完整 pairs | 99 |
| 完整 pose pairs（过滤后） | 14,391 |
| 受影响 jobs | 98 |
| 受影响 candidates | 83 |
| OPEN_TRAIN | 226 |
| OPEN_DEVELOPMENT | 32 |
| open teacher 合计 | 258 |
| test32 raw files / metrics / labels | 0 / 0 / 0 |

关键哈希：

```text
teacher:
89ad82c7cde28d862fecedfff4559e810bab68cf2405aa8f9e4dc5f1bd148068

teacher audit:
533bec24823f991a8249f2115c8e31e4efbb94c05b5528390ca5060fe9b54d26

archive:
21f00fc17b153dadb2dcd93d90f24a28c4161ccddfe1876c90f0c21ab6a0467d
```

本地内容寻址交付：

```text
experiments/phase2_5080_v1/prepared/
pvrig_v4_d_dev1_open258_v1_2/delivery_dev1_v1_2/
current_dev1_v1_2/
```

### 2.2 open258 冻结单体结构输入

从原 Docking job manifest 中只选择 `OPEN_TRAIN` 与 `OPEN_DEVELOPMENT`，提取每条候选在 Docking 前已经冻结的 VHH 单体 PDB：

| 项目 | 数值 |
|---|---:|
| 冻结 monomer PDB | 258 |
| 唯一 monomer hash | 258 |
| OPEN_TRAIN | 226 |
| OPEN_DEVELOPMENT | 32 |
| sealed monomer opened | 0 |
| Docking result / pose / geometry label read | 0 |

结构输入 archive SHA256：

```text
9faa35b6a73872e37fd2f19a2919fab3f5512e5750a8d8251dd6a7c4340a18b7
```

### 2.3 结构特征

每条 monomer 提取 126 个刚体旋转/平移不变描述符，包括：

- ALL、FRAMEWORK、CDR1、CDR2、CDR3、CDR_ALL；
- CA radius of gyration 和 pair-distance quantiles；
- path length、end-to-end、tortuosity；
- non-local CA contact density；
- shape eigenvalue fractions；
- 单体置信度/B-factor 分布；
- CDR–CDR 和 CDR–framework 几何。

特征结果：

```text
rows: 258
features: 126
all finite: true
test32 labels accessed: 0

feature table SHA256:
37b6fbc4b947f2598dd83ac1a742a9382d36e13aa641a5f460e3050d17e83472
```

## 3. 冻结模型比较

在读取 candidate-level OPEN_DEVELOPMENT 标签前冻结以下比较：

| 模型 | 输入 |
|---|---|
| M0 parent-only | parent cluster + design mode + target patch one-hot |
| M1 sequence-only | frozen ESM2 + VHHBERT + physicochemical mean-pooled embedding，共 1,115 维 |
| M2 structure-only | 126 个冻结 monomer 几何特征 |
| M3 sequence+structure | 1,115 维 sequence embedding + 126 维 structure feature |

训练协议：

```text
OPEN_TRAIN: 226 rows / 20 parent clusters
OPEN_DEVELOPMENT: 32 rows / 3 unseen parent clusters
parent-cluster overlap: 0

Ridge alpha:
0.01, 0.1, 1, 10, 100, 1000
仅在 OPEN_TRAIN 内做 5-fold parent-group CV

ensemble seeds:
43, 53, 67, 79, 97
```

实现冻结 SHA256：

```text
aa786374955d6c8c555acce3df5295cf69b55aea11a1b6dc917f6fa6711fcef2
```

## 4. OPEN_DEVELOPMENT 结果

主目标：`R_dual_min`

| 模型 | Spearman | Pearson | MAE | NDCG | Top 20% Recall |
|---|---:|---:|---:|---:|---:|
| M0 parent-only | 0.1653 | 0.1564 | 0.04447 | 0.9722 | 0.2857 |
| M1 sequence-only | 0.0740 | 0.2160 | 0.03797 | 0.9828 | 0.2857 |
| **M2 structure-only** | **0.5806** | **0.6036** | **0.03208** | **0.9885** | 0.2857 |
| M3 sequence+structure | 0.1518 | 0.3061 | 0.03655 | 0.9857 | 0.2857 |

M3 相对 M1 的 paired candidate bootstrap：

```text
median Spearman delta: +0.0742
95% CI: [-0.0500, +0.2008]
positive fraction: 0.8882
replicates: 5000
```

产物：

```text
experiments/phase2_5080_v1/runs/
pvrig_v4_d_structure_fusion_surrogate_v1/
```

## 5. 当前结论

### 5.1 VHH 单体结构确实提供了明显信号

在 3 个完全未见 parent clusters、32 条 development 候选上，M2 的：

```text
Spearman = 0.5806
Pearson  = 0.6036
MAE      = 0.0321
```

明显优于本轮 mean-pooled sequence Ridge。这说明单体 CDR 形状、CDR 间相对布局、紧致度和 framework 支撑几何，能够解释相当一部分 Docking 连续几何差异。

### 5.2 但简单拼接不是正确融合方式

M3 只达到 `Spearman=0.1518`，远低于 M2。最可能的工程原因是：

```text
1,115 维 sequence embedding
+
126 维 structure feature
+
仅 226 个 fit rows
```

在单一 Ridge 中产生强烈维度不平衡和共线性，结构信号被高维序列表征稀释。

### 5.3 还不能称为生产前筛 PASS

原因：

1. development 只有 32 条、3 个 parent clusters；
2. M3-M1 的 bootstrap 95% CI 仍跨 0；
3. 四个模型的 Top 20% recall 都只有 0.2857；
4. M2 优势主要在整体连续排序和误差，不是高分尾部富集；
5. 当前 teacher 来自 formal evaluator FAIL 后的 development-only V1.2 修复分支。

因此可以说：

> 单体结构值得进入下一版模型。

不能说：

> 现有结构模型已经能可靠筛出 blocker 或替代 Docking。

## 6. 下一步执行规划

### 第一优先：结构 late-fusion V1.1

不再修改本次 V1。另起版本，只使用 OPEN_TRAIN 内部 group-CV 做所有选择：

```text
sequence model
structure model
分别训练
    ↓
OOF prediction-level late fusion
或 structure residual correction
    ↓
固定融合权重
```

不能继续用同一 32 条 development 反复挑权重；新版本应以 V4-H 或另一批 prospective candidates 作为验证。

### 第二优先：改善高分尾部目标

在 train-only parent-group CV 中增加：

```text
pairwise ranking loss
top-20%-weighted regression
NDCG / enrichment objective
```

但 `R_dual_min` 连续回归仍保留为主标签，不能改成事后 G1–G5 硬分类。

### 第三优先：两级大库前筛

```text
全库 sequence-only cheap screen
→ Top 800–1,500 做 NanoBodyBuilder2/IgFold 单体结构
→ structure-only / late-fusion rerank
→ Top 100–300 进入双受体 Docking
```

当前结果支持把结构作为第二级 reranker，而不是一开始就替代 sequence model。

### 第四优先：用 V4-H 扩充独立 teacher

截至本记录刷新时，V4-H research lane：

```text
SUCCESS jobs: 1,176
FAILED_MAX_ATTEMPTS: 4
RUNNING: 10
seed917 双受体成功 candidate entities: 584
完整 6-job candidate entities: 0
```

V4-H 继续运行。完成后应按新的冻结协议形成下一批独立 teacher/holdout，用于检验 M2 和新的 late-fusion，而不是继续反复使用当前 32 条 development。

## 7. 总结

本轮已经完成了一个关键验证：

> **使用 VHH 冻结单体结构，确实比当前 mean-pooled sequence Ridge 更接近 Docking 的 `R_dual_min`。**

当前最好的 development 模型是 structure-only Ridge，而不是简单 sequence+structure 拼接。下一步应围绕“结构 late fusion + 高分尾部排序 + V4-H 新数据验证”推进，同时保持 test32 sealed 和 computational-geometry-only 的证据边界。
