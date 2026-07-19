# PVRIG Docking 与实验评分口径校准方案

## 0. 当前无实验数据时的执行口径

在 BLI、Kd、IC50 全部缺失时，不能确认任何计算分数与真实实验量之间的映射，也不能输出可信的绝对 Kd/IC50。当前应建立“计算代理金标准”，目标限定为：

```text
稳定富集同时满足以下条件的候选：
1. 多模型支持可能结合 PVRIG；
2. 多构象、多随机种子 Docking 可重复；
3. VHH 占据 PVRIG–PVRL2 功能界面；
4. 界面能量和物理几何合理；
5. 序列和单体结构可开发性风险较低。
```

### 0.1 把未来实验评分改写成计算代理评分

未来初筛口径：

```text
BLI 70% + 表达量 20% + 纯度 10%
```

当前只能改写为：

```text
计算初筛分 = 0.70 × BindingConsensus
             + 0.20 × ExpressionRiskProxy
             + 0.10 × PurificationRiskProxy
```

- `BindingConsensus`：DeepNano、NABP-BERT、NanoBind 等序列结合模型，加上独立结构/界面证据的共识排名。
- `ExpressionRiskProxy`：基于 VHH 序列、结构置信度、疏水暴露、聚集倾向、异常电荷和已知表达风险的代理分数。
- `PurificationRiskProxy`：聚集、非单体、极端 pI、游离 Cys、化学修饰位点和结构不稳定风险；它不是对真实纯度百分比的预测。

不同模型的原始概率不能直接平均。应在同一候选批次内转换成 percentile/rank-normalized 分数，再取中位数或训练前冻结的加权共识。

未来复筛口径：

```text
Kd 50% + IC50 50%
```

当前只能改写为：

```text
计算复筛分 = 0.50 × AffinityConsensus
             + 0.50 × BlockerGeometryConsensus
```

- `AffinityConsensus`：HADDOCK/Rosetta 界面能量、界面面积、氢键/盐桥、clash、独立亲和力模型或 affinity-range 模型的共识排名。
- `BlockerGeometryConsensus`：双构象 `R_dual_min`、PVRL2 界面遮挡、热点覆盖、CDR3 遮挡和多 seed 重复性。

二者必须分开。一个候选可以拥有好看的界面能量但不占据 PVRL2 界面，也可以几何上挡住界面但形成不稳定的复合物。

### 0.2 无实验条件下如何确认计算评价器

按以下五层证据逐级确认：

1. **通用 pose-recovery benchmark**：选取具有公开原生复合物结构的 nanobody–antigen 集合，拆开后重新 Docking，报告 DockQ、iRMSD、lRMSD、Fnat 和 top-N 可接受姿势恢复率。
2. **PVRIG 靶点阳性/阴性控制**：将 HR-151 作为已知 PVRIG 序列阳性，但不能把它当作已知原生姿势；配套使用无关 VHH、CDR3 shuffle、CDR 热点 alanine mutant 等计算阴性/扰动控制。
3. **双构象、多 seed 稳定性**：8X6B、9E6Y 分开 Docking，每个构象至少多个 seed；报告 seed 间 Spearman、top-K Jaccard、分数 MAD 和姿势聚类模态占比。使用中位数或下置信界，禁止取最好一次。
4. **正交评分共识**：HADDOCK、Rosetta/独立界面能量、几何遮挡、序列结合模型分别形成独立证据通道。只有多个通道共同支持才进入最高层级。
5. **扰动一致性测试**：破坏 PVRIG 热点、VHH CDR3 接触残基或将 VHH 从界面移开后，阻断几何与界面分数应系统性下降；若不下降，评分器没有学到目标机制。

无实验阶段建议使用分级标签，不使用“预测 Kd=某数值”或“预测 IC50=某数值”：

```text
Tier A：多模型结合支持 + 双构象阻断 + 多 seed 稳定 + 能量合理
Tier B：阻断几何较好，但结合/能量或重复性证据不足
Tier C：可能结合，但不覆盖 PVRIG–PVRL2 界面
Tier D：技术失败、明显 clash、不稳定或只有单次偶然高分
```

### 0.3 当前项目的特殊边界

- 8X6B/9E6Y 定义 PVRIG–PVRL2 界面和受体构象差异，不提供 VHH 的原生结合姿势。
- HR-151 是可用的 PVRIG 序列阳性；若没有其复合物结构，只能评价“能否被流程富集”，不能做 target-specific native pose recovery。
- 当前 `R_dual_min` 适合做保守阻断几何弱标签，不等于结合概率、Kd、IC50 或实验阻断率。
- 旧 Docking Gold V1.3 没有通过 bootstrap 模态稳定性门槛，因此新评价器必须先通过多 seed 姿势模态和排名稳定性检验，才能作为大规模代理训练标签。

## 1. 核心结论

当前尚无实验数据时，Docking 可以作为候选筛选的“临时计算金标准”，但它本质上仍是阻断几何弱标签。获得 BLI、Kd 和 IC50 后，应反过来用实验结果校准 Docking，而不是用 Docking 证明实验结果。

建议同时保留两套标签：

1. **生物学标签**：BLI、pKd、pIC50、最大阻断率（Emax）。用于评价 Docking 是否真的富集结合或阻断候选。
2. **综合参赛标签**：在生物学通过后，加入表达量、纯度和可开发性，用于决定最终提交顺序。

Docking 本身不预测表达量和纯度，因此不应只用“70% BLI + 20% 表达量 + 10% 纯度”的总分来校准 Docking；必须分别报告 Docking 对 BLI、Kd、IC50 的关系。

## 2. 初筛：先过硬门槛，再计算 70/20/10 排名

拟定口径：

```text
初筛综合分 = 0.70 × BLI_norm + 0.20 × Expression_norm + 0.10 × Purity_norm
```

这个权重可作为第一版预注册方案，但必须先设置硬门槛：

```text
表达量通过
AND 纯度通过
AND BLI 信噪比/特异性通过
AND 传感器 loading、reference 和曲线质量通过
```

任一硬门槛失败即不进入加权排名。高表达量或高纯度不能“补偿”无结合，强 BLI 信号也不能“补偿”明显聚集、低纯度或非特异结合。

### 2.1 BLI 单浓度分数

建议满足：

- 所有样品使用相同的有效摩尔浓度；若使用粗上清，BLI 信号会与表达量强烈混杂，不能再把表达量作为独立 20% 简单相加。
- 使用 reference subtraction，记录 target channel、reference channel、loading level、association endpoint、dissociation endpoint 和基线漂移。
- 设置无关蛋白或非相关 VHH 的反筛，排除黏性/非特异性结合。
- BLI 分数按同板阳性和阴性对照归一化，而不是直接使用原始 nm shift。

示例：

```text
BLI_norm = clip((R_sample - median(R_negative)) /
                (median(R_positive) - median(R_negative)), 0, 1)
```

单浓度应选在阳性参考样品动态范围中部附近，避免所有强候选都进入饱和区。建议随机抽取 10%–20% 候选做 2–3 个浓度，检查单点排序是否与小型剂量曲线一致。

### 2.2 表达量和纯度

建议把表达量做对数转换，避免极高表达量支配总分：

```text
Expression_log = log10(Expression + epsilon)
```

再按冻结的参考区间或同批稳健分位数映射到 0–1。纯度可使用分段 desirability：低于硬门槛为失败，达到目标纯度后封顶，不鼓励从 95% 到 99% 的小差异压过明显的结合差异。

## 3. 复筛：Kd 与 IC50 使用对数尺度，并加入 Emax/曲线质量门槛

不能直接对原始 Kd 和 IC50 做线性加权。二者都是“越小越好”，且通常跨多个数量级，应先转换：

```text
pKd   = -log10(Kd [M])
pIC50 = -log10(IC50 [M])
```

原拟定口径：

```text
复筛分 = 0.50 × pKd_norm + 0.50 × pIC50_norm
```

在以下硬门槛之后，这个 50/50 方案是可用的：

```text
Kd 曲线质量通过
AND IC50 曲线质量通过
AND 最大阻断率 Emax 通过
AND IC50 位于实际测试浓度范围内
```

若“阻断 PVRIG–PVRL2”是最终主要目标，更推荐：

```text
复筛分 = 0.40 × pKd_norm + 0.50 × pIC50_norm + 0.10 × Emax_norm
```

或者保留正式的 50/50 权重，但把 Emax 设为硬门槛。低 IC50 但最大阻断平台很低的部分抑制剂，不应被视作强阻断候选。还应保留 kon、koff；相同 Kd 可能来自完全不同的动力学组合。

IC50 建议用阳性/阴性对照归一化后的抑制率拟合 4PL。每条有效曲线至少应在 IC50 两侧都有实测点；超出浓度范围的结果作为 `<LLOQ` 或 `>ULOQ` 的删失值保存，不能强行赋一个精确数值。

## 4. 如何证明 Docking 评分真的有效

### 4.1 前瞻、盲法、覆盖完整分数范围

不能只实验验证 Docking 前排，否则无法估计假阴性，并会高估富集效果。首批实验应按 Docking 分层抽样，例如：

| 组别 | 建议比例 | 目的 |
|---|---:|---|
| Docking 高分 | 40%–50% | 测量实际 top-K 命中率 |
| Docking 中分 | 20%–25% | 评估排序梯度 |
| Docking 低分 | 10%–15% | 估计假阴性 |
| 高不确定性/高多样性 | 10%–15% | 防止模型只学习既有偏好 |
| 阳性、阴性和参考对照 | 每板重复 | 监测板间漂移和动态范围 |

抽样和 Docking 阈值应在揭盲实验结果前冻结。还应按母框架簇、生成方法、CDR3 长度和设计 patch 分层，避免某一框架垄断高分组。

### 4.2 必须报告的评价指标

连续结果：

- Spearman rho、Kendall tau：Docking 排名与 BLI、pKd、pIC50、Emax 的相关性。
- 分组 bootstrap 95% CI：以母框架簇或 parent_id 为重采样单位。
- 每个 Docking 分数十分位的实验命中率和实验指标分布。

二分类实验通过/失败：

- PR-AUC：阳性比例较低时比只看 ROC-AUC 更有意义。
- Precision@K、Recall@K、Top 1%/5%/10% hit rate。
- EF1%、EF5%、EF10%：衡量实际最关心的早期富集。
- 若输出实验阳性概率，再报告 calibration curve 和 Brier score。

### 4.3 对现有 Docking 口径做消融

至少比较：

1. HADDOCK 总分或界面能单独使用；
2. 8X6B 单分支；
3. 9E6Y 单分支；
4. 双构象较弱分支 `R_dual_min`；
5. 严格 Class-A 几何规则；
6. 多随机种子的中位数；
7. 中位数减去种子离散惩罚；
8. 几何 + 能量 + 重复性联合模型。

当前 `R_dual_min` 取双构象较弱分支，适合作为保守型阻断几何指标。Stage 2 多随机种子完成后，建议使用：

```text
Docking_stable = median(R_dual_min across seeds)
                 - lambda × MAD(R_dual_min across seeds)
```

`lambda` 必须在训练集内部确定，并在独立实验批次验证；不能根据最终实验结果反复调到最好。

## 5. 权重如何确认，而不是凭感觉决定

### 第一阶段：冻结专家权重

先预注册并冻结：

```text
初筛：70/20/10，且先过硬门槛
复筛：50/50，且先过曲线质量和 Emax 门槛
```

这套权重用于首批前瞻实验，避免事后挑权重。

### 第二阶段：数据学习权重

积累实验数据后，用非负约束的 logistic regression、ordinal/ranking model 或多任务模型学习权重。训练时：

- 按 parent_framework_cluster 分组切分；
- 使用 nested group cross-validation；
- 保留独立、未参与调权的 prospective holdout；
- 比较学习权重与冻结 70/20/10、50/50 在 holdout 上的 Precision@K、EF5%、PR-AUC 和校准误差。

只有学习权重在独立批次中稳定优于冻结权重，才升级评分版本。

## 6. 推荐的数据表字段

每条候选至少保留：

```text
candidate_id
parent_framework_cluster
sequence_sha256
R_8X6B_seed*
R_9E6Y_seed*
R_dual_min_seed*
docking_seed_median
docking_seed_MAD
HADDOCK_score
hotspot_overlap
total_occlusion
CDR3_occlusion
clash_metric
expression_raw
purity_raw
BLI_raw
BLI_reference_raw
BLI_normalized
Kd_M
kon
koff
IC50_M
Emax_percent
curve_fit_error
assay_batch
plate_id
experimental_pass
```

原始值、归一化值、门槛结果和最终分数必须分列保存，不能只保留一个综合分。

## 7. 建议的版本判定

Docking 评价器可以升级为“经实验校准”版本，至少应满足：

1. 独立实验批次的 top-K 命中率明显高于随机抽样；
2. EF5% 或 EF10% 的 bootstrap 95% CI 下界仍大于 1；
3. 对 pIC50/Emax 的排序关系在多个母框架簇中方向一致；
4. 多随机种子评分稳定，且低分抽样组确实包含更少实验阳性；
5. 预注册权重与数据学习权重的比较在独立 holdout 上完成；
6. 所有失败和超范围结果按删失/技术失败处理，不能静默改成阴性。

在满足以上条件前，应称其为“Docking 阻断几何弱标签评价器”，不能称为实验阻断金标准或 Kd 预测器。

## 8. 参考规范

- NCBI Assay Guidance Manual：Assay Operations for SAR Support
  - https://www.ncbi.nlm.nih.gov/books/NBK91994/?report=reader
- NCBI Assay Guidance Manual：Data Standardization for Results Management
  - https://www.ncbi.nlm.nih.gov/sites/books/NBK91993/
- NCBI Assay Guidance Manual：Preface / assay validation principles
  - https://www.ncbi.nlm.nih.gov/sites/books/NBK92019/
- Sartorius Octet BLI method resources
  - https://www.sartorius.com/en/products/biolayer-interferometry/bli-resources
