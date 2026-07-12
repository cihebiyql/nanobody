# PVRIG 微调监督：Docking Teacher 当前决策与正式下一阶段

更新时间：2026-07-12 22:35 Asia/Shanghai

## 1. 结论

**是，V3-P 微调前应先生成 PVRIG Docking teacher 数据。** 但当前已经完成了这一工作的单 parent `pilot96`，所以下一步不是继续把 pilot96 当正式训练集反复调模型，而是立即生成 **多 parent、预先分层抽样的 400-600 条正式 prospective teacher**。

正确依赖顺序是：

```text
冻结 teacher 定义和抽样规则
→ 40-60 个 parent framework 生成 8,000-12,000 条候选
→ 快速硬筛后分层抽取 400-600 条 prospective teacher
→ Node1 单体结构 + HADDOCK + 双参考几何 + residue contacts
→ 按 parent_framework_cluster 冻结 train/dev/test
→ V3-P formal
→ 再以 300-500 条主动学习数据补充边界和不确定区域
```

V3-G 的 target-dependence 加强可以与正式 teacher 生成并行进行；不需要等 V3-G 完全成熟后才开始 docking。V3-P formal 训练则必须等正式多 parent teacher 冻结后开始。

## 2. 当前已经完成并验证的状态

| 层 | 当前结果 | 结论边界 |
| --- | --- | --- |
| 候选 | 96 条，96 个唯一序列；A/B/C/D patch 各 24 条 | 全部来自 `h-NbBCII10`，只有 1 个 parent cluster |
| 单体与 docking | 96/96 monomer/QC/HADDOCK 完成 | 8X6B receptor 生成 pose |
| 唯一 pose | 813 条；每候选 4-10 条 | 不补造缺失 pose，不重复计算 `.pdb`/`.pdb.gz` 同 stem 文件 |
| 双参考后处理 | 813/813 完成 8X6B、9E6Y 和 consensus | 9E6Y 是同批 8X6B pose 的重评分，不是独立 docking |
| residue contact | 813/813 提取成功 | docking-derived soft labels，不是晶体结构 contact 真值 |
| 候选闭包 | selection、candidate、pose、contact、teacher manifest 均覆盖相同 96 个 ID | 审计 PASS |
| 泄漏 | 对 11 条已知阳性做 exact-sequence 比对，重叠为 0 | 阳性及其衍生突变仍保持 calibration-only |
| 可复现性 | 五个 teacher 主产物复跑 SHA256 全部不变 | 字节级确定性 PASS |
| 测试 | Phase2 完整测试 `216/216` 通过 | 代码与数据管线验证 |

pose 级标签分布：

```text
G1:   6
G2: 200
G3: 535
G4:   0
G5:  72
合计: 813
```

候选级 provisional stable tier：

```text
G2: 36
G3: 56
G5:  4
```

候选最佳单 pose tier：

```text
G1:  5
G2: 44
G3: 47
```

这再次说明不能把 `A/A = 1，其他 = 0` 当训练标签；应学习 G1-G5 有序层级、连续几何量和 Top-K 稳定性。

## 3. pilot96 证明了什么

pilot96 已经证明：

1. Node1 能从候选序列稳定完成 monomer、HADDOCK 和双参考后处理；
2. 每条候选可生成 candidate、pose 和 residue-contact 三个层级的 teacher 数据；
3. 4-10 个实际 unique poses 可以被无伪造地聚合；
4. V3-P 的 ordinal、geometry regression 和 contact-frequency 多头可以共同前向、反向和推理；
5. teacher 文件可重建且哈希稳定。

pilot96 **没有** 证明：

1. 模型能泛化到未见 parent framework；
2. docking tier 等于真实 PVRIG binding 或 PVRL2 blocking；
3. 9E6Y 是独立构象 docking 复现；
4. 当前 V3-P1 可以用于生产排序；
5. 当前单 seed、单 parent 的 dev 指标可以作为正式性能声明。

## 4. V3-P1 smoke 的正确解释

当前 V3-P1 在 RTX 5080 上完成 76 train / 20 dev 的单 parent smoke：

| 指标 | 结果 |
| --- | ---: |
| Ordinal MAE | 0.5372 |
| 常数基线 MAE | 0.5408 |
| Ordinal Spearman | 0.5273 |
| Teacher relevance Spearman | 0.9265 |
| Top-K A/B fraction Spearman | 0.6890 |
| 8X6B hotspot Spearman | 0.4644 |
| 9E6Y hotspot Spearman | 0.4774 |
| 8X6B CDR3 occlusion Spearman | 0.8909 |
| 9E6Y CDR3 occlusion Spearman | 0.8641 |
| 8X6B total occlusion Spearman | 0.4212 |
| 9E6Y total occlusion Spearman | -0.4363 |

结论是：多任务管线有学习信号，但 ordinal 只略胜常数基线，9E6Y total-occlusion 分支失败。正式状态仍是：

```text
PASS_PIPELINE_SMOKE_COMPLETED
NOT_READY_SINGLE_PARENT_PILOT_ONLY
```

因此现在不应利用 pilot96 继续寻找一个看似更高的随机拆分分数；更高优先级是获得多 parent teacher 和显式双 conformer 输入。

## 5. 正式首批 teacher 的数据定义

### 5.1 候选母库

```text
40-60 个 parent framework
× 3 个 PVRIG patch
× 至少 2 种设计模式
→ 8,000-12,000 条原始候选
→ 快速硬门后约 5,000-9,000 条
```

parent 应覆盖不同 framework cluster、CDR3 长度、电荷、疏水比例和设计方法。每条候选必须保存 parent、patch、method、seed、设计前后 CDR 和序列哈希。

### 5.2 500 条 prospective teacher 的互斥抽样层

建议先冻结以下互斥配额，再查看 docking 标签：

| 抽样层 | 数量 | 目的 |
| --- | ---: | --- |
| 通用 contact/interface 高分 | 140 | 提高 G1/G2 富集机会 |
| 中间分数/决策边界 | 100 | 学习排序边界 |
| 低分但 fast QC 通过 | 60 | 获得计算失败模式 |
| parent/patch/method/CDR3 最大多样性 | 120 | 防止生成器和 parent 偏差 |
| 多模型冲突、seed 分歧或高不确定性 | 80 | 提前覆盖主动学习区域 |
| 合计 | 500 | prospective formal teacher |

同时执行：

```text
同一 parent <= 8-10 条
同一 parent + patch + method <= 3-4 条
每个 patch 和主要 design method 均有覆盖
所有 CDR3 长度区间均有覆盖
```

已知阳性家族的 50 条左右校准突变应作为 **额外 calibration-only 批次**，不占上述 500 条 prospective 配额，也不进入正式 train/dev/test。

## 6. 在启动正式 docking 前必须冻结的内容

正式批次开跑前先生成并哈希：

```text
formal_teacher_candidate_manifest.tsv
formal_teacher_sampling_config.json
parent_cluster_split_assignment.tsv
teacher_schema.json
docking_and_geometry_config.json
input_sha256.tsv
```

其中必须固定：

- `parent_framework_cluster` 和 train/dev/test/challenge 分配；
- 8X6B/9E6Y 结构版本和链映射；
- HADDOCK 版本、restraint、Top-K 和 clustering 规则；
- contact cutoff、pose weighting 和 G1-G5 映射；
- 实际 pose 不足 10 条时的处理规则；
- known-positive / derivative 的 leakage exclusion；
- claim boundary。

先按 parent cluster 冻结 split，再运行和查看标签，可避免看见 tier 分布后移动 parent 造成选择泄漏。

## 7. 正式 Node1 teacher 生产规范

对 400-600 条正式候选：

```text
NanoBodyBuilder2 monomer + QC
→ 8X6B receptor HADDOCK
→ 每条保留实际 Top 4-10 unique poses
→ 8X6B 几何评分
→ 9E6Y 参考界面重评分
→ Top-K / cluster 稳定性
→ VHH-PVRIG residue contact-frequency
```

另从 parent、patch、tier 和方法分层选 100-150 条做 **独立 9E6Y receptor docking**，用于量化“同 pose 重评分”和“独立构象 docking”之间的偏差。它不应被默认为全量 9E6Y 真值。

每条候选至少输出：

```text
G1-G5 ordinal target
8X6B and 9E6Y tier probabilities/metrics
topk_AA_fraction
topk_A_or_B_fraction
blocker_supporting_cluster_count
pose_cluster_entropy
best_pose_vs_median_gap
hotspot overlap
total/CDR3 occlusion
PVRIG-specific contact-frequency matrix
teacher completeness and claim boundary
```

## 8. 正式训练就绪门

只有同时满足以下条件才进入 V3-P formal：

1. 至少 400 条 prospective candidates 完成全部 teacher 字段；
2. 至少 40 个 parent frameworks，且 parent cluster split 无交叉；
3. selection、candidate、pose、contact、split manifest ID 完全闭包；
4. contact extraction 成功率目标为 100%，最低不得低于 99%；
5. 已知阳性及衍生突变与 prospective train/dev/test 零 exact-sequence 重叠；
6. G1-G5 不被压缩为 A/A 二分类；
7. 训练前冻结正式 test 和生成方法 challenge block；
8. teacher 主产物可重复构建且 SHA256 稳定。

如果 G1/G2 太少，应增加高先验、模型冲突和新 patch 的第二轮 docking，不得通过放宽标签定义来人工制造正例。

## 9. V3-G 和 V3-P 同步需要修正的模型项

在正式 teacher 生产期间并行完成：

1. 加强 V3-G 的 target-swap、hotspot-mask shuffle 和 antigen-ablation；
2. 将 8X6B 和 9E6Y 作为两个显式 residue/structure conformer 通道；
3. 保留 residue contact head，不退回 mean pooling 单头；
4. 第一版冻结 ESM2/VHHBERT，仅训练 cross-attention、pooling 和小 ranker；
5. 正式评估使用 3 个 seed、parent-cluster test、bootstrap 和 permutation；
6. 主指标使用 G1+G2 Recall@20%、EF@10%、NDCG 和连续 geometry Spearman。

## 10. 接下来按什么顺序做

### P0：pilot 收口（已完成）

- 96/96 docking；
- 813/813 双参考和 contact；
- 数据闭包、泄漏、哈希和 216 项测试审计；
- V3-G1/V3-P1 smoke。

### P1：正式候选母库（现在开始）

- 从 Top 200 / clean 1591 中冻结 40-60 个代表 parent；
- 生成 8,000-12,000 条带完整 provenance 的 PVRIG 条件化设计；
- 运行 fast hard gate。

### P2：预注册首批 500 teacher

- 按本文件的互斥配额分层抽样；
- 冻结 parent-cluster split、challenge block、teacher schema 和所有哈希。

### P3：Node1 正式 teacher 生产

- 跑 400-600 条全流程；
- 同步最小运行证据；
- 聚合 candidate/pose/contact 三层数据；
- 做 100-150 条独立 9E6Y 子集。

### P4：V3-P formal

- 使用加强后的 V3-G residue backbone；
- 加入显式 8X6B/9E6Y conformer features；
- 训练三 seed ordinal/contact/geometry 模型和小 ranker；
- 只在冻结 test 上做一次正式评估。

### P5：主动学习

- 再选择 300-500 条高分、高不确定、模型冲突和新空间候选；
- 冻结第二批 teacher；
- 最终形成约 800-1,000 条 PVRIG-specific teacher。

## 11. 当前禁止事项

- 不把 pilot96 当作 production-ranking 训练集；
- 不把 docking teacher 写成 binding/blocking 实验真值；
- 不用 `A/A = positive`、其余全负的二分类；
- 不只学习 rank-1 pose；
- 不把 9E6Y 重评分描述成独立 9E6Y docking；
- 不把已知阳性 CDR 相似度作为模型输入；
- 不让通用 Kd 预测成为 PVRIG 前筛主目标。

## 12. 关键证据路径

```text
experiments/phase2_5080_v1/audits/pvrig_teacher_pilot96_sync_audit.json
experiments/phase2_5080_v1/audits/pvrig_teacher_pilot96_postprocess_audit.json
experiments/phase2_5080_v1/audits/pvrig_teacher_pilot96_audit.json
experiments/phase2_5080_v1/audits/PVRIG_TEACHER_PILOT96_AUDIT.md
experiments/phase2_5080_v1/prepared/pvrig_teacher_pilot96/candidate_summary.csv
experiments/phase2_5080_v1/prepared/pvrig_teacher_pilot96/pose_summary.csv
experiments/phase2_5080_v1/prepared/pvrig_teacher_pilot96/pose_contact_frequency.jsonl
experiments/phase2_5080_v1/runs/phase2_v3_p1_pilot_smoke/phase2_v3_p1_pilot_smoke_20260712_222211_seed83/summary.json
```

最终判断：**Docking teacher 确实应先于 V3-P 正式微调生成；pilot 阶段已经完成，当前真正的第一优先级是多 parent 正式候选库和首批 500 条预注册 teacher，而不是继续优化单 parent smoke 分数。**
