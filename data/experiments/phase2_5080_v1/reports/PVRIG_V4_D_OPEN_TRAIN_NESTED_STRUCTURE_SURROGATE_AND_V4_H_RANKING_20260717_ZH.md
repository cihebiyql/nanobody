# PVRIG V4-D OPEN_TRAIN 嵌套结构代理与 V4-H 研究排序执行报告

日期：2026-07-17

## 1. 本轮目标与证据边界

本轮执行的目标是：

```text
VHH 序列 + 冻结单体结构
→ 便宜的 sequence/structure surrogate
→ 逼近独立 8X6B/9E6Y Docking 的连续几何主目标 R_dual_min
→ 在不读取 V4-H Docking 结果的前提下，对 1320 条研究候选先行排序
```

这里的输出只能解释为：

```text
对独立双受体 computational docking geometry 的代理估计
```

不能解释为：

```text
Docking Gold
PVRIG 结合概率
Kd/affinity
PVRL2 competition 真值
实验阻断概率
正式比赛提交结论
```

V4-D 原 formal evaluator 的失败结论不变；V4-F test32 继续 sealed；legacy128 未合并。

## 2. 训练数据如何隔离

V4-D V1.2 open teacher 共 258 条：

| split | 数量 |
|---|---:|
| OPEN_TRAIN | 226 |
| OPEN_DEVELOPMENT | 32 |

为避免在已经看过一次的 32 条 OPEN_DEVELOPMENT 上继续调参，本轮首先物理生成只含 OPEN_TRAIN 的输入：

```text
prepared/pvrig_v4_d_open_train_model_inputs_v1_1/
├── open_train226_primary_v1_1.tsv
├── open_train226_sequence_manifest_v1_1.csv
└── open_train226_model_inputs_v1_1.receipt.json
```

训练标签表 SHA256：

```text
8fb90b20e6f939989ef2c3e5fee3fba184217ec0a094cf33c48c4996e2df9ef8
```

随后只对这 226 条序列重新计算真实 frozen embedding，未加载旧的 7088 条全集缓存：

| 通道 | 维度 |
|---|---:|
| VHHBERT mean pool | 768 |
| ESM2 mean pool | 320 |
| physicochemical | 27 |
| 合计 | 1115 |

RTX 5080 实际生成 226 条 embedding 用时约 50 秒，输出 1 个 shard；V4-F test32 sequence/embedding/label 访问均为 0。

## 3. 模型与验证设计

训练集包含 226 条候选、20 个 parent framework cluster。没有进行随机行拆分，而是使用 whole-parent nested cross-validation：

```text
outer 5-fold parent-group CV
  → inner 5-fold 选择 Ridge alpha / fusion weight
  → M5 residual 使用额外 sub-inner 5-fold 构造无泄漏 residual target
```

比较四个模型：

| 模型 | 定义 |
|---|---|
| M1 | 1115 维 frozen sequence embedding + Ridge |
| M2 | 126 维单体结构 invariant descriptors + Ridge |
| M4 | prediction-level convex late fusion |
| M5 | structure base + cross-fitted sequence residual correction |

结构特征包括 CDR1/2/3、CDR_ALL、framework 和全分子的：

- confidence 分布；
- CA radius of gyration；
- pair-distance quantiles；
- path/end-to-end/tortuosity；
- non-local contact density；
- shape eigenvalue fractions；
- CDR–CDR 与 CDR–framework 几何。

冻结 preregistration：

```text
audits/phase2_v4_d_open_train_nested_late_fusion_v1_1_preregistration.json
SHA256 cabcff4f17cd5a27a5a8b248b2a247c2f39b49dce9b06f1f950db0929e7d7ecf
```

冻结 implementation：

```text
audits/phase2_v4_d_open_train_nested_late_fusion_v1_1_implementation_freeze.json
SHA256 c6a93b056f63bc172d10c6c8fca39507a5cbff4c6dd89c4a500eb9f8170c0f11
```

## 4. OPEN_TRAIN nested OOF 结果

主目标：`R_dual_min`。

| 模型 | Spearman | Pearson | MAE | NDCG | Top20% recall |
|---|---:|---:|---:|---:|---:|
| M1 sequence-only | 0.5921 | 0.5074 | 0.03169 | 0.98318 | 0.3696 |
| **M2 structure-only** | **0.6868** | **0.5978** | **0.02877** | **0.98678** | **0.4348** |
| M4 late fusion | 0.6803 | 0.5942 | 0.02878 | 0.98677 | 0.4348 |
| M5 structure + sequence residual | 0.6587 | 0.5487 | 0.03038 | 0.98615 | 0.3696 |

parent-group bootstrap：

| 比较 | median ΔSpearman | 95% CI | Δ>0 比例 |
|---|---:|---:|---:|
| M4 − M1 | +0.0789 | [-0.0075, +0.2170] | 0.9610 |
| M4 − M2 | -0.0064 | [-0.0146, +0.0004] | 0.0340 |
| M5 − M2 | -0.0258 | [-0.0736, +0.0040] | 0.0438 |

结论：

1. 单体结构特征确实提供了比 sequence-only 更强的 docking-geometry 代理信号；
2. 简单 late fusion 没有超过 structure-only；
3. sequence residual correction 也没有改善；
4. 在全部 226 条 OPEN_TRAIN 上重新选择全量 scoring artifact 时：

```text
fusion_structure_weight = 1.0
residual_gamma = 0.0
```

即两个自适应组合都退化为 **M2 structure-only**。这是当前冻结的领先 scorer。

运行回执：

```text
audits/phase2_v4_d_open_train_nested_late_fusion_v1_1_runtime_receipt.json
SHA256 c21f18bf159732893401c3762dd8ca287093e32a4d283fb530a1ec2af7d573a0
```

## 5. V4-H 1320 条 label-free 结构准备

V4-H 候选来源：

```text
prepared/pvrig_v4_h_research_pool_v1/outputs/research_ready1320.tsv
SHA256 f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551
```

完整性：

- 1320 条唯一 candidate；
- 1320 条唯一 sequence/sequence SHA；
- 11 个 parent，每个 120 条；
- 3 个 patch，每个 440 条；
- H3/H1H3 各 660 条；
- 66 个 parent×patch×mode strata，每层 20 条。

Node23 的 1320 个冻结 monomer PDB 已只读同步并验证：

- candidate/sequence/PDB composite key 1320/1320；
- PDB hash/size 1320/1320；
- regular、non-symlink；
- source chain 全部为 A；
- 未读取 Docking result/status/pose/test32。

结构输入 manifest：

```text
prepared/pvrig_v4_h_research1320_structure_inputs_v1/
  research1320_structure_inputs_v1.tsv
SHA256 099a8360e07cb724d3790d33349c1e54df57f5d675e50875df1c1b2f7aa90711
```

随后为全部 1320 条提取了同一套 126 维 invariant structure features：

```text
prepared/pvrig_v4_h_research1320_structure_features_v1/
  research1320_structure_features_v1.tsv
SHA256 c778c420792c095073d0cbf2e60e754ff5c1273e8c032eb06104223db8e365a5
```

验证：1320 行、1320 唯一 candidate、126 特征、全部 numeric finite、geometry label read=0。

## 6. V4-H 先验排序已冻结

用冻结的 M2 structure-only full-train scorer 对 1320 条 V4-H 进行 label-free 评分：

```text
predictions/pvrig_v4_h_research1320_structure_surrogate_v1/
  v4h_research1320_structure_surrogate_ranking_v1.tsv
SHA256 f864c675db2c9ec449e52a7debacdd283ff5d404f40b6abfbd9cb0ef3e6b9d5a
```

预测分布：

| 统计量 | predicted R_dual_min |
|---|---:|
| min | 0.4930 |
| q05 | 0.5110 |
| q10 | 0.5175 |
| median | 0.5573 |
| q90 | 0.5822 |
| q95 | 0.5997 |
| max | 0.6165 |

该 ranking 在读取任何 V4-H Docking geometry label 之前生成；运行回执：

```text
audits/phase2_v4_h_research1320_structure_surrogate_v1_runtime_receipt.json
SHA256 6e7d688ad2f05b8686f727501415e786f82d060c0305178e725c129d91353645
```

## 7. V4-H 1320 条 sequence-only 对照已完成

为判断“使用 VHH 单体结构是否真的带来额外信息”，本轮又在完全不读取 V4-H Docking 结果的条件下，对同一 1320 条序列重新计算：

| 通道 | 维度 |
|---|---:|
| VHHBERT mean pool | 768 |
| ESM2 mean pool | 320 |
| physicochemical | 27 |
| 合计 | 1115 |

输入清单被物理隔离为：

```text
prepared/pvrig_v4_h_research1320_sequence_inputs_v1/
  research1320_sequence_manifest_v1.csv
SHA256 9d5004b362ad9b51c5bfd11eec4c9e6c2313cc61554b6fe7d15a39a9f796207f
```

真实 embedding 在 RTX 5080 上生成，用时约 35 秒：

```text
VHHBERT (1320, 768)
ESM2    (1320, 320)
physchem(1320, 27)
```

三组数组全部 finite，1320 条 `vhhbert_available` 全为 true。随后使用已冻结的 OPEN_TRAIN226 `M1_SEQUENCE_ONLY` Ridge 评分：

```text
predictions/pvrig_v4_h_research1320_sequence_surrogate_v1/
  v4h_research1320_sequence_surrogate_ranking_v1.tsv
SHA256 a87d37d9edf130b2eb82e301746d52abee4a56fd7babf5bde4b5b0eefcc92fbc
```

预测分布：

| 统计量 | predicted R_dual_min |
|---|---:|
| min | 0.4948 |
| q05 | 0.5121 |
| q10 | 0.5223 |
| median | 0.5540 |
| q90 | 0.5901 |
| q95 | 0.6010 |
| max | 0.6154 |

评分器在第一次真实 V4-H sequence score 前冻结：

```text
audits/phase2_v4_h_research1320_sequence_surrogate_v1_implementation_freeze.json
SHA256 87c0a664fd58fc1881df41aedeb58273122e439cdea15214acef30610f322675
```

## 8. Sequence 与 structure 的 label-free 对照

两个冻结模型在 1320 条上的预测相关性：

| 指标 | 值 |
|---|---:|
| prediction Pearson | 0.8404 |
| prediction Spearman | 0.7747 |

Top-N 重合：

| Top-N | 重合数 | 重合比例 | Jaccard |
|---:|---:|---:|---:|
| 20 | 6 | 30% | 0.1765 |
| 50 | 30 | 60% | 0.4286 |
| 100 | 78 | 78% | 0.6393 |

解释：

1. sequence 和 structure 对大的 parent-level 趋势相当一致；
2. 结构特征仍显著改变最顶部候选的次序，Top20 只有 6 条重合；
3. 这与 OPEN_TRAIN nested OOF 中 M2 优于 M1 的结果一致，但还不能证明 V4-H 上 M2 一定更准；
4. 真正比较准确度必须等 terminal teacher 后按冻结 evaluation prereg 一次性评估。

为了避免 raw Top-N 的 parent/patch/mode collapse，已额外生成 132 条均衡诊断组合：

```text
11 parents × 3 patches × 2 modes × 2 candidates = 132
```

每个 stratum 包含：

- 1 条两个模型共同高分的 `CONSENSUS_HIGH`；
- 1 条 sequence/structure 排名分歧最大的诊断候选。

组合分布严格闭合：

```text
每个 parent 12 条
每个 patch 44 条
H3/H1H3 各 66 条
```

文件：

```text
reports/pvrig_v4_h_research1320_sequence_structure_comparison_v1/
  v4h_research1320_sequence_structure_balanced132_v1.tsv
SHA256 a700adc22920d28c9dcddfabb5512dd125a047c771a0c47cb2e8315f830ab842
```

这 132 条只是诊断/组合覆盖，不是实验有效性或最终提交排名。

## 9. 当前最重要的新问题：parent concentration

M2 structure-only 原始排名出现明显 parent concentration：

```text
Top 20  ：20/20 来自 C0283
Top 50  ：50/50 来自 C0283
Top 100 ：100/100 来自 C0283
```

同时 Top100 的 patch 和 mode 仍较均衡：

```text
patch: A_CENTER 32, B_LOWER 35, C_CROSS 33
mode : H3 51, H1H3 49
```

M1 sequence-only 也表现出相同方向：

```text
Top 20  ：20/20 来自 C0283
Top 50  ：50/50 来自 C0283
Top 100 ：90 条 C0283，10 条 C0360
```

这说明 C0283 优势不是单体结构描述符单独制造的；sequence embedding 同样把它置于最前。但两个模型在部分 parent 内并不稳定：例如 C0086、C0176 的候选内 prediction Pearson 接近 0 或略为负值，而 C0162、C0409、C0417 则较高。

这说明当前排序的主要风险不是 patch/mode collapse，而是模型可能主要利用 parent-level monomer geometry。

因此：

1. 不能把 raw Top-N 直接当作候选组合；
2. 后续必须报告 global correlation 和 within-parent correlation；
3. 最终 portfolio 必须限制单 parent 占比；
4. V4-H Docking 完成后要检验 C0283 的 parent-level 优势是真实几何信号还是结构模型偏差。

## 10. Node23 当前状态

2026-07-17 19:10（Asia/Shanghai）只读检查：

```text
SUCCESS             1730 jobs
RUNNING                12 jobs
FAILED_MAX_ATTEMPTS      4 jobs
PENDING               6456 jobs（包括尚未启动的后续 seed）
total manifest        8202 jobs
```

当前第一阶段 controller 选择了 2640 个 candidate seed-917 jobs，其中约 65.5% 已成功；12 个 job 并行，Node23 load1 约 42/64 CPU。adaptive/controller 进程均存活。四个失败均为技术失败，不应改当前协议或事后放宽阈值；现有 V4-H 链继续运行。

## 11. 下一步

### 立即保持冻结

- 不再使用同一 226 条 OPEN_TRAIN 调结构特征、alpha 或 fusion weight；
- 不读取 partial V4-H geometry 来挑模型；
- 保持 V4-F test32 sealed；
- 保持当前 ranking hash 不变。
- 保持 sequence、structure 和 comparison 三组 hash 不变。

### V4-H terminal 后的 research evaluation

在 V4-H 形成单一 immutable continuous-geometry teacher 后，一次性评估：

1. 全体 analyzable candidate 的 Spearman/Pearson/MAE/NDCG/Top20 recall；
2. 11 个 parent 内的 Spearman，再做 macro average；
3. parent-centered correlation；
4. patch/mode 分层；
5. C0283 与其他 parent 的真实 `R_dual_min` 分布；
6. 技术不完整 candidate 单独报告，不做数值填补。

并同时比较：

1. M1 sequence-only 与真实 teacher；
2. M2 structure-only 与真实 teacher；
3. 两模型 consensus；
4. 132 条均衡诊断组合中的 consensus 与 disagreement 子集。

上述 terminal evaluator 已在任何 V4-H geometry value 解封前实现并冻结：

```text
audits/phase2_v4_h_research1320_sequence_vs_structure_terminal_evaluation_v1_preregistration.json
SHA256 2bfd76ef451a8576077fe92ba5ef6fc82d053eeb46d79c35080ab762e3b080c8

audits/phase2_v4_h_research1320_sequence_vs_structure_terminal_evaluator_v1_implementation_freeze.json
SHA256 7c7b15171f2922e7f2de4edb6868930ae6525968b91e4947b55368a22dea2759
```

评估器只接受带 terminal receipt 和显式 SHA256 的单一 immutable teacher；`TECHNICAL_INCOMPLETE` 行的 `R_dual_min` 必须为空，禁止数值填补。这样 Node23 完成后无需再看结果决定指标或改评估方法。

terminal teacher adapter 也已在解封前冻结：

```text
audits/phase2_v4_h_research1320_terminal_teacher_v1_implementation_freeze.json
SHA256 bdf63f163d51408bd510331da5a26b3fbf2e3c17d324da3b6a0357f887bdfa43
```

它只接受 Node23 的 `ADAPTIVE_DOCKING_RECEIPT.json` 与 `final_adaptive_seed_ranking.tsv` 同时满足：四阶段 terminal count 闭合、receipt/ranking 哈希一致、1320 candidate key 闭合、`R_dual_min=min(median_8X6B, median_9E6Y)`。因此后续解封是机械执行，不需要再根据结果修改 teacher 规则。

## 12. 用户授权的 partial-success 全链路预览

用户随后明确要求拉取当前已经成功的 Docking 结果并测试完整流程。因此已建立独立的非 terminal preview lane；从这一时点起，操作者不再是 V4-H geometry-label-blind，最终 terminal 结果只能作为冻结协议下的研究确认，不能再称 untouched prospective evidence。

快照：

```text
1,923 status-SUCCESS jobs
1,901 scorer-valid jobs
22 SCORING_INVALID jobs
937 PARTIAL_ANALYZABLE candidates
383 PARTIAL_INCOMPLETE candidates
```

937 条 partial 结果：

| 模型 | Spearman | Pearson | MAE | Top20% recall |
|---|---:|---:|---:|---:|
| M1 sequence-only | 0.5240 | 0.4947 | 0.03444 | 0.3989 |
| M2 structure-only | **0.5667** | **0.5310** | **0.03365** | **0.4574** |

M2−M1 parent-bootstrap ΔSpearman 中位数为 `+0.04138`，95% CI `[+0.01419,+0.09730]`。parent-centered Spearman 从 M1 的 `0.1389` 提升到 M2 的 `0.1977`。

但 coverage 严重受 job 顺序影响：C0176 当前为 0/120，C0283 仅 29/120。因此不能据此调模型或阈值，仍需等待 terminal teacher。

详见：

```text
reports/PVRIG_V4_H_PARTIAL_SUCCESS_PREVIEW_V1_1_20260717_ZH.md
```

### 模型升级路线

如果 structure-only 在 V4-H 中仍稳定：

```text
M2 invariant structure Ridge
→ 增加 parent-centered / within-parent ranking objective
→ 加结构置信度与 training-manifold distance uncertainty
→ 再测试 gated sequence+structure fusion
```

如果 global 好但 within-parent 差，则模型只能用于 parent/scaffold 级优先级，不能用于同 parent 内挑序列。

如果 global 和 within-parent 都好，才把它接入更大候选库，作为 full docking 前的结构代理前筛；最终仍须经过真实 Node1/HADDOCK/PVRL2 occlusion 漏斗。
