# PVRIG VHH Docking 数据盘点与 10k 训练集扩展方案

更新时间：2026-07-19

## 1. 当前数据规模

统计单位固定为唯一 VHH 序列（标准化氨基酸序列 SHA256），不能把 pose、双构象或重复 seed 当作新增序列。

| Campaign | 唯一序列 | 候选 Docking jobs | 说明 |
|---|---:|---:|---|
| RFantibody docking1024 | 1,024 | 1,024 | 旧口径，多 pose；9E6Y 主要为 overlay，不是独立双构象 docking |
| Teacher500 | 500 | 500 | 旧口径；其中 290 条后来进入 V4-D 独立双构象复算 |
| V3 Dual128 | 128 | 768 | RF1024 的子集；2 构象 × 3 seeds，Evaluator PASS |
| V4-D FullQC290 | 290 | 1,740 | Teacher500 的子集；2 构象 × 3 seeds；连续分数可分析，但 categorical threshold-sensitivity gate FAIL |
| V4-H adaptive | 1,320 | 3,664 | Stage1 全量；Stage2/3 为同一序列重复 seed |
| V4-I | 1,962 | 4,924 | Stage1 全量；Stage2 为 500 条重复 seed |

去重结果：

- 做过任一种 Docking 的唯一序列：**4,806**
- 做过独立 8X6B/9E6Y 双构象 Docking 的唯一序列：**3,700**
- 独立双构象候选 jobs：**11,096**
- 加上旧 RF1024/Teacher500 后，候选 Docking jobs：**12,620**
- 成功完成的候选 Docking jobs：**12,609**

独立双构象候选级连续标签：

- 可形成双构象连续分数：**3,580**
- 排除 V4-D formal evaluator FAIL 后：**3,290**
- 多 seed 稳定性标签：**1,258**（含 V4-D）；排除 V4-D 后 **968**
- V4-H/V4-I 技术不完整、不能形成 R_dual_min：**120**

旧 RF1024 和 Teacher500 可作为低权重 auxiliary/legacy labels，但不能与独立双构象标签无差别混合。

## 2. V4-I Stage2 已观察到的规律

分析范围：476 条完整双构象 × 双 seed 候选。

### 2.1 重复 seed 的稳定性有限

- seed917 与 seed1931 的 R_dual_min Spearman：0.476
- Pearson：0.507
- 两个 seed 的 Top10 仅重合 1/10
- Stage1 Top10 与双 seed 综合 Top10 重合 4/10
- seed dispersion 中位数 0.0219，P95 0.0520

结论：单 seed 可以粗筛，但不适合作为高位次精确排序金标准。

### 2.2 scaffold/parent 是最强的表观规律

在 Stage2 富集队列中，parent framework cluster 可解释约 45.9% 的 R_dual_min 方差。
Top50 中 C0176 占 18 条，C0348 占 10 条。

高分 lineage：

- C0176 / PLDNANO_VHH_00257：中位 R_dual_min 0.6341，Top20% 富集 2.19 倍
- C0283 / PLDNANO_VHH_00423：中位 0.6212，富集 1.33 倍
- C0348 / PLDNANO_VHH_00508：中位 0.6189，富集 1.19 倍
- C0148 / PLDNANO_VHH_00211：中位 0.6211，富集 1.14 倍

这既是可利用信号，也是最大的 shortcut/leakage 风险。训练/测试必须按 parent cluster 与近 CDR3 family 分组。

### 2.3 生成路线和设计模式

全局观察：

- MPNN：中位 0.6182；Top20% 富集 1.23 倍
- LATENT：中位 0.6083；Top20% 富集 0.67 倍
- H3-only：中位 0.6189；Top20% 富集 1.23 倍
- H1H3：中位 0.6103；Top20% 富集 0.74 倍
- 最富集组合：MPNN + B_LOWER + H3，Top20% 富集约 1.84 倍
- MPNN + A_CENTER + H3，Top20% 富集约 1.67 倍

但在相同 parent/patch/mode 内配对后，MPNN 相对 LATENT 的中位增益仅约 0.0035；H3 相对 H1H3 的中位增益约 0.0039。因此 source/mode 不是跨 scaffold 的绝对规则。

### 2.4 CDR3 长度

当前队列中 CDR3 18–20 aa，尤其 20 aa，较容易取得高阻断样几何分数；CDR3 长度与 R_dual_min 的全局 Spearman 为 0.45。

但 CDR3 长度和 parent scaffold 强烈相关；在 parent 内部，相关性中位数降至约 0.12。不能简单生成大量 20 aa CDR3 并宣称更优。

## 3. 6000 条新增序列是否合理

合理，但要区分目标。

若新增 6,000 条均做一个 seed 的独立双构象 Docking：

- 新增候选 jobs：12,000
- 按 V4-I 约 95.9% 可分析率，预计得到约 5,750 条有效 paired labels
- 与 3,290 条当前同类标签合并，约 9,040 条
- 若纳入 V4-D 研究标签，约 9,330 条
- 若再纳入旧 RF1024/Teacher500 的异构 weak labels，可超过 10k，但标签口径不统一

所以：

- “10k 广义 weak labels”：新增 6,000 条足够
- “10k 同口径、可形成 R_dual_min 的有效标签”：建议提交约 7,000 条，而不是 6,000 条
- “10k 多 seed 强标签”：远远不够，需要额外重复 docking

## 4. 新增 6000 条的推荐组成

不要全部从当前 Top lineage 做局部优化。

| 数据类型 | 比例 | 数量 | 目的 |
|---|---:|---:|---|
| 高分 exploitation | 30% | 1,800 | 利用 C0176/C0283/C0348/C0148 等高分 lineage |
| 匹配 hard negatives / counterfactuals | 30% | 1,800 | 相同 parent、长度、QC，只改变界面/CDR，防止模型学 scaffold shortcut |
| scaffold 与 CDR 多样性探索 | 25% | 1,500 | 新 parent cluster、低覆盖 CDR3 长度、C_CROSS、LATENT 等 |
| 当前模型高不确定/模型分歧 | 10% | 600 | 主动学习，扩大决策边界 |
| 突变阶梯和机制对照 | 5% | 300 | 同一候选逐步破坏 hotspot、CDR3 接触或构象，提供局部排序监督 |

约束：

- 每个 parent cluster 不超过新增库的 5–8%
- 至少覆盖 40–50 个 parent clusters
- CDR3 14–20 aa 都应保留；18–20 aa 可以富集，但不能垄断
- A_CENTER/B_LOWER 可略增权；C_CROSS 不能删除
- 保持 H3/H1H3、MPNN/LATENT 的配对反事实设计
- 通过 Full-QC、表达/可开发性代理过滤后再 docking，但不能只保留模型预测高分序列

## 5. Docking 测量设计

### 第一层：所有 6000 条

- 8X6B 独立 docking，seed917
- 9E6Y 独立 docking，seed917
- 共 12,000 candidate jobs
- 不允许用 8X6B pose overlay 代替 9E6Y 独立 docking

### 第二层：1500 条分层重复

不要只重复 Top1500。建议：

- 各 score decile 分层随机共 1,000 条
- Top 候选 250 条
- 近边界/高不确定/模型分歧 250 条

每条增加 seed1931 的双构象，共 3,000 jobs。

### 第三层：300 条第三 seed

选择高分、高 seed dispersion、模型分歧和机制对照，共 300 条增加 seed3253，600 jobs。

候选 jobs 总量约 15,600。标准 47 个 protocol controls 应按同一批次重复，但永远不进入候选训练行。

## 6. 应保存的训练标签

每个唯一序列一行，至少保存：

- sequence、sequence_sha256、CDR1/2/3、parent_framework_cluster、near_cdr3_family
- generator/source、target_patch、design_mode、QC/developability
- 每个 seed 的 job_score_8X6B、job_score_9E6Y
- median_R8、median_R9
- R_dual_min = exact min(R8, R9)
- R_dual_mean、R_dual_gap
- seed_dispersion_8X6B、seed_dispersion_9E6Y
- hotspot/holdout overlap
- total occlusion、CDR3 occlusion、CDR3 fraction
- VHH-PVRIG clash、模型数量、native/cross agreement
- technical_failure_mask、missing_seed_mask
- protocol_version、scorer_hash、receptor_hash

不要只保留一个最终 docking score。

## 7. 模型训练建议

建议训练多任务 sequence-to-docking-surrogate，而不是直接命名为实验阻断模型：

1. 主任务：R8、R9 回归
2. 硬约束输出：R_dual_min = min(R8, R9)
3. 辅助任务：R_dual_gap、seed dispersion、技术失败概率、界面几何分量
4. 排序损失：同 parent/counterfactual pair 的 pairwise ranking
5. 不确定性：heteroscedastic regression 或 ensemble disagreement

证据权重建议：

- 三 seed、formal PASS：最高
- 两 seed：高
- 单 seed：中低
- V4-D formal gate FAIL：单独 protocol/domain 标记，研究性纳入
- RF1024/Teacher500 overlay/旧协议：低权重 auxiliary，不作为同口径主标签
- protocol controls：完全排除训练

数据切分：

- 按 parent framework cluster + near-CDR3 family 分组
- 70% train / 15% development / 15% prospective test
- test cluster 在查看新 docking 标签前冻结
- 禁止随机逐序列切分

评价：

- Spearman / Kendall
- NDCG、Top1%/Top5% recall
- 在固定 docking 预算下的高分富集
- parent-held-out 泛化
- seed-repeat consistency
- uncertainty selective risk
- 与 parent-only、CDR3-length-only、metadata-only shortcut baseline 比较

## 8. 推荐执行顺序

1. 先构建 4,806 条去重 master table，并按协议层级选择主标签。
2. 用当前 3,290 条同口径标签训练 V0，建立 parent-only、CDR3-only、ESM/序列模型基线。
3. 从大规模生成池中按 exploitation、hard-negative、diversity、uncertainty 规则选 6,000–7,000 条。
4. 冻结 candidate manifest、parent-group split、scorer 和 receptor hashes。
5. 运行第一 seed 双构象 docking。
6. 基于预注册的分层方案选择 1,500 条第二 seed，而不是事后只挑高分。
7. 构建 V1 模型并在预先冻结的 parent-held-out prospective set 上评估。
8. 模型输出必须称为“计算阻断样几何/潜在阻断排序”，不是实验 blocking probability。
