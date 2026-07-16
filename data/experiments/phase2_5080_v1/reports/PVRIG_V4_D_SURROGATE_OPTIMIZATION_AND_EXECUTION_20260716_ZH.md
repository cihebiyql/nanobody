# PVRIG V4-D Surrogate 优化与执行路线

**更新时间：** 2026-07-16 15:15 CST  
**主目标：** 用便宜的 VHH 序列模型逼近独立 8X6B/9E6Y Docking 的连续阻断几何结果，用于大库前筛。  
**证据边界：** 模型输出只是 computational docking-geometry surrogate，不是 PVRIG 结合概率、Kd、PVRL2 competition 或实验阻断真值。

## 1. 当前结论

现在最大的瓶颈不是 GPU，也不是网络太小，而是：

1. 独立双受体 Docking teacher 尚未完成；
2. 当前训练集只有 226 条、20 个 parent clusters；
3. 7,087 条候选中，2,643 条被局部标记为 `IN_DOMAIN`，但当前 support 总门禁仍为 FAIL；
4. 小数据下过早解冻 ESM2/VHHBERT 或上更大 cross-attention，更容易学到 parent、CDR3 长度或生成器风格。

因此当前正确的优化顺序是：

```text
完成 V4-D 真实 teacher
→ 低复杂度 baseline/contact/embedding/fusion 公平比较
→ 冻结模型和 V4-F 预测
→ V4-F 未见 parent 正式评估
→ 主动学习增加 parent 和支持域覆盖
→ 数据量达标后再尝试 tiny MLP / residue cross-attention
```

## 2. 实测运行状态

### 2.1 Node23 V4-D

2026-07-16 15:10 CST 快照：

```text
2022 total jobs
417 SUCCESS
9 RUNNING
1596 not-yet-created/pending states
0 FAILED
```

分层情况：

```text
controls: 282/282 SUCCESS
OPEN_TRAIN: 135 SUCCESS + 9 RUNNING
OPEN_DEVELOPMENT: 0 touched
PROSPECTIVE_COMPUTATIONAL_TEST: 0 touched
```

Controller PID 265751 存活，HADDOCK/CNS 正在运行。当前不修改 controller、scratch、并发数或 job order。

由于远程 job priority 在后段会将 open 与 test32 交错，test32 保守降级为 computational challenge；真正未触达的正式 prospective holdout 是 V4-F 96。

### 2.2 Node1 Deep-QC 和 V4-F

```text
Top100 Deep-QC: FULL_TNP
8 TNP chunks x 4 requested cores
V4-F Full-QC watcher: WAITING_UPSTREAM
V4-F panel: 96 candidates / 4 completely unseen parent clusters
```

V4-F 将对全部 96 条运行 Full-QC；之后对所有 hard-pass 候选运行独立双受体 Docking，不按模型分数二次挑选，失败后不从 panel 外补位。

## 3. 已经完成的模型资产

### 3.1 基础 sequence surrogate

已实现：

- OPEN_TRAIN 226 拟合；
- OPEN_DEVELOPMENT 32 选型；
- parent-cluster 隔离；
- sequence/length/parent/metadata shortcut baselines；
- parent bootstrap ensemble 和 uncertainty；
- 原子发布、artifact replay 和 hash receipt；
- 没有 sealed test label 输入参数。

### 3.2 Frozen embedding surrogate

已实现：

```text
ESM2 mean-pooled ridge
VHHBERT mean-pooled ridge
ESM2 + VHHBERT joint ridge
CDR-length-only shortcut
```

Embedding bank 含 7,087 条 VHH 和 1 条 PVRIG target，共 7,088 条。当前训练代码已可用，但因 open258 teacher receipt 尚未出现，正式训练会 fail-closed，不会使用临时或不完整标签。

### 3.3 Residue/contact 特征 V3

2026-07-16 已用本地 RTX 5080 完成正式重算：

```text
rows: 7087
columns: 125
seeds: 43 / 53 / 67
receipt verification: PASS
CSV SHA256: f48de64d253a76bc9cff19ab1348c1655be7306828289b28f9a04e5b95471e7d
audit SHA256: eb63f16aacef2ed3d7ed0a755bfc3c49a590e09248b28643b94dc7e2c4e27e29
receipt SHA256: b12c0ff0ce6760db7169ec3616dddaf05786e5ca795354f639ef2bf87c370e2b
```

V3 已强制闭合 candidate/cache/mask/checkpoint/hotspot 身份，且已将两个严重编码 CDR 长度的 raw contact-mass 列标记为 diagnostic-only。旧 V1/V2 release 已移入 quarantine，未删除。

### 3.4 稳定 contact schema V2

已经在不读取 Docking label 的前提下，按三种 seed 的稳定性冻结 12 个特征：

```text
paratope_mean
paratope_cdr_mean
paratope_cdr3_mean
paratope_cdr3_max
paratope_cdr_mass_fraction
contact_global_mean
contact_hotspot_weighted_mean
contact_hotspot_fraction
contact_cdr_hotspot_weighted_mean
contact_cdr3_hotspot_weighted_mean
contact_noninterface_mean
contact_interface_specificity
```

冻结 schema：

```text
prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json
SHA256: 22d11cdccb0af6ecb26eb3bdcbae6c35dc5bc57543d662cf9da94155ee746cc0
```

## 4. 下一步的模型比较

在 open258 teacher 释放后，只运行一次冻结比较：

| 模型 | 作用 |
| --- | --- |
| sequence/CDR length only | 检查是否只学了长度 |
| parent only | 检查是否只记住 scaffold |
| design metadata only | 检查是否只识别 patch/method |
| sequence feature ridge | 低成本序列 baseline |
| ESM2 ridge | 通用蛋白 embedding baseline |
| VHHBERT ridge | VHH 专用 embedding baseline |
| joint embedding ridge | 两种 embedding 融合 |
| stable contact mean ridge | 只用 12 个稳定 contact mean |
| stable contact mean+std ridge | 加入 contact seed 不确定性 |
| embedding+contact fusion ridge | 当前主候选 |

当前不上大型 MLP，不解冻 PLM，不使用 G1-G5 硬分类作主标签。V4-D 的冻结主目标仍是 `R_dual_min`；多目标连续回归应当另起新版本，不在看到 V4-D dev/test 结果后回改当前协议。

## 5. 模型门禁

开放开发集上至少检查：

1. overall Spearman 是否超过最强 shortcut；
2. parent-macro Spearman 是否改善；
3. held-out parent clusters 中是否至少 2/3 不退化；
4. uncertainty 高的样本是否真的更容易出错；
5. contact/fusion 是否超过 length-only、parent-only 和 embedding-only；
6. artifact replay 与 prediction hash 是否完全一致。

如果 open gate 失败：

```text
冻结 FAIL
不改门槛
不挑最好的 seed
不解封或反复利用 test32
不广泛用于 7087 排名
直接转入主动学习增加 teacher
```

当前 support audit 的总门禁为 FAIL，因此即使 open model gate 通过，2,643 条 `IN_DOMAIN` 也不得立即进入 production exploitation，只能用于研究性排序和 acquisition。只有新预注册 support 版本通过 null/coverage 门禁后，才能在其通过的子集上做受限 exploitation；其余候选继续走 uncertainty/diversity/direct-docking 路线。

## 6. V4-F 正式评估

在 V4-F 任何 Docking label 被打开前，先冻结：

```text
model configuration
teacher/split/feature/embedding hashes
open-development summary
96-row predictions
prediction SHA256
```

然后一次性评估 4 个完全未见 parent clusters。报告必须同时给出：

- overall metrics；
- per-parent metrics；
- per-CDR3-length metrics；
- Full-QC attrition；
- in-domain/near-domain 分层；
- uncertainty selective-risk。

## 7. 主动学习扩充

建议下一批预注册约 296 条，它们是 acquisition set，不是评估集：

### 7.1 已见 parent：200 条

20 个 OPEN_TRAIN parent，每个 10 条：

```text
4  predicted top
3  high uncertainty / model disagreement
2  generic-prior vs geometry-surrogate conflict
1  middle/low-score QC-pass control
```

### 7.2 未见 parent：96 条

```text
8 unseen parent clusters
x 3 target patches
x 2 design modes
x 2 candidates
= 96
```

另外保留至少 2 个 parent clusters 不进入 acquisition，用作下一版 formal holdout。

排除：

- V4-D 290；
- V4-F 96；
- 所有已知阳性、patent anchors 和 calibration mutants；
- exact sequence/CDR 近重复；
- Full-QC hard fail。

如果 V4-D open gate 失败，上述 predicted-top 配额改为 feature-diverse 和 generic-prior high/mid/low 分层，不得假设失败模型仍有效。

## 8. 什么时候才值得上更复杂模型

至少同时满足：

```text
>= 500 independent candidate teachers
>= 30 parent clusters
untouched unseen-parent formal holdout
continuous dual-receptor targets complete
support/OOD audit has a new preregistered version
ridge/fusion baselines frozen
```

第一个复杂升级只建议两层 tiny ordinal/regression MLP，而不是全量解冻 ESM2/VHHBERT。只有它在 untouched parent 上显著超过 ridge，并通过 target-shuffle、parent-only、length-only 对照，才能继续引入 residue-level cross-attention。

## 9. 与抗体生成路线的衔接

生成路线与 surrogate 训练路线保持独立：

```text
RFantibody / fixed-pose ProteinMPNN / AntiFold
→ Fast QC / Full QC
→ support/OOD 判定
→ support 总门禁通过后的 in-domain: surrogate exploitation + uncertainty quota
→ near/OOD: diversity + direct Docking
→ 真实 Docking 结果追加为新 teacher
→ 重训下一版 surrogate
```

生成器输出不能自动成为正标签，模型高分也不能代替真实 Docking。这样才能形成可迭代但不自我循环污染的闭环。

## 10. 当前正在执行的工作

1. V4-D 2022 jobs 继续运行，不干扰远程 controller；
2. Node1 Deep-QC 继续运行，V4-F watcher 等待自动启动；
3. residue/contact V3 已完成并验证；
4. contact schema V2 已冻结；
5. contact/fusion trainer 已完成，定向测试 8/8 PASS，正式输入预检 PASS；
6. open258 teacher-ready 训练 watcher 已完成并在 tmux `pvrig-v4d-surrogate-training` 中运行，当前为 `WAITING_OPEN_TEACHER`；teacher receipt 到达后将自动运行基础、embedding 和 contact/fusion 模型。

## 11. 停止条件

V4-D 当前版本在任一情况下应停止扩展：

- remote evaluator 不是 PASS；
- open258 teacher 行数、split 或 hash closure 不一致；
- 发现 test raw label 进入特征、调参或排名路径；
- 所有候选模型都不能超过最强 shortcut；
- uncertainty 不能识别高风险预测；
- V4-F 未见 parent 结果明显失效。

这些失败都应当触发“增加独立 teacher 和 parent 覆盖”，而不是临时改门槛或换更大网络。
