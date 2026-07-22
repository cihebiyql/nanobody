# PVRIG VHH 计算亲和力排序方案

日期：2026-07-22

## 1. 结论先行

当前没有任何一个已测试方法，能够把 PVRIG VHH 按真实 Kd 稳定排序。最合理的路线不是寻找一个“万能 Kd 模型”，而是建立分层证据：

1. **100 万序列层**：DeepNano 等只作为弱结合先验，不作 hard gate；
2. **15 万单体结构层**：TNP 只评价结构可开发性，不推断亲和力；
3. **约 5,000 个复合物层**：双受体 Docking 后，用 Rosetta InterfaceAnalyzer、PRODIGY、FoldX 和姿势稳定性做多方法秩共识；
4. **约 200–500 个同 parent 候选层**：用 Rosetta Flex ddG 评价相对于 parent 的亲和力变化；
5. **约 50–200 个最终候选层**：可增加短程 MD + MM/GBSA，但仍只作为相对排序证据，不报告为预测 Kd。

Rosetta 最有价值的用途是：

- InterfaceAnalyzer：评价复合物界面的能量和几何；
- Flex ddG：在同一 parent、同一参考 pose 下评价突变相对 ΔΔG；
- SnugDock/RosettaDock：优化或重采样复合物 pose。

Rosetta 原始能量不能直接等同于实验 Kd，也不应直接用于跨 scaffold 的绝对亲和力排序。

## 2. bxcpu 当前状态

固定姿势路线前 150,000 条 VHH 的 NanoBodyBuilder2 结构预测已完成：

- 150,000/150,000 有归档结果；
- 4 个 wave 全部完成；
- 32 个节点归档均已在 Node1 独立 SHA256 验证；
- Node1 持久目录：
  `/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722`
- 本地控制目录：
  `/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722`

最初的“Node1 归档经本机再传回 bxcpu”路线在 WSL/Windows-SSH 的 rsync 增量流上发生协议损坏；源归档未受影响，但继续搬运 5.5 GB 结构既慢又没有计算价值。当前已切换为 **bxcpu 就地重建结构并立即运行 TNP** 的 v2 路线：

- NBB2 临时结构 worker：
  `pvrig_500k_generation_20260721/scripts/run_bxcpu_nbb2_ephemeral_for_tnp.slurm`
- TNP worker：
  `pvrig_500k_generation_20260721/scripts/run_bxcpu_tnp_generic.slurm`
- 提交脚本：
  `pvrig_500k_generation_20260721/scripts/submit_bxcpu_tnp_recompute150k.sh`
- 原始结果安全清理：
  `pvrig_500k_generation_20260721/scripts/cleanup_bxcpu_tnp_recompute.py`
- 全量聚合器：
  `pvrig_500k_generation_20260721/scripts/aggregate_tnp_fixed_pose150k.py`
- 运行目录：
  `pvrig_500k_generation_20260721/run/pvrig_1m_fixed_pose_top150k_tnp_recompute_bxcpu_v2_20260722`

该路线每波使用 8 个 CPU 节点；NBB2 既往实测每波约 21–30 分钟。此前 305,705 条大分片 TNP 约 9 分钟，本次每个节点约 5,000 条时实测仅约 1.3–1.4 分钟。每波完成精确 ID 聚合后才删除这次重算的临时 PDB；Node1 上原有 150,000 条哈希归档保持不动。

截至 2026-07-22 17:47：

- wave_00 已完成：40,000/40,000 TNP `PASS`，精确 ID 集匹配；
- wave_00 NBB2 8 个节点耗时约 25.6–27.1 分钟；
- wave_00 TNP 8 个节点耗时约 1.3–1.4 分钟；
- exact-ID 聚合和 SHA256 通过后，已清理本次重算的约 5.7 GB 临时 PDB；
- wave_01 已在 8 个节点运行；wave_02、wave_03 将由同一控制器自动串行接续；
- 本地同步 watcher 已运行，最终 150,000 条聚合完成后会自动回传本地并同步 Node1。

TNP 输出必须解释为结构可开发性代理，不是实测表达量或纯度。

## 3. 已有 PVRIG 阳性校准结果

阳性面板包含 11 条 VHH，其中 10 条有已知 Kd，5 条有 blocking IC50；每条阳性有 9 个冻结 HADDOCK pose，共 99 个 pose。

### 3.1 序列模型

与已知 pKd 的相关性：

| 方法 | Pearson | Spearman | 当前用途 |
|---|---:|---:|---|
| DeepNano | 0.173 | 0.321 | 弱结合先验 |
| NanoBind-seq | 0.004 | -0.115 | 不用于亲和力排序 |
| DeepNano + NanoBind 均值 | 0.040 | 0.091 | 不优于 DeepNano |
| NanoBind-affinity midpoint | 0.184 | 0.311 | 区间系统偏弱，只作诊断 |

文件：

- `results/pvrig_positive11_binding_prior_20260719/POSITIVE11_BINDING_PRIOR_EVALUATION_ZH.md`
- `results/pvrig_positive11_binding_prior_20260719/evaluation_metrics.json`

### 3.2 结构方法

| 方法 | Pearson | Spearman | family 方向 | 结论 |
|---|---:|---:|---:|---|
| PRODIGY pose 中位数 | 0.389 | 0.310 | 4/6 | 弱 pose-dependent 先验 |
| FoldX AnalyseComplex | 0.366 | 0.236 | 2/6 | 不作跨候选主排序 |
| FoldX fixed-parent ΔΔG | 0.129 | 0.100 | 2/5 | 同 parent 诊断 |
| Graphinity 单点加和 | -0.976 | -0.949 | 1/4 | 拒绝进入排序 |

PRODIGY 对绝对 pKd 的 MAE 为 2.478 log10；不能作为预测 Kd。

文件：

- `results/pvrig_positive11_structure_affinity_benchmark_20260719/PVRIG_POSITIVE_AFFINITY_METHOD_BENCHMARK_ZH.md`
- `results/pvrig_positive11_structure_affinity_benchmark_20260719/final_method_comparison.tsv`
- `results/pvrig_positive11_structure_affinity_benchmark_20260719/final_evaluation_metrics.json`

### 3.3 当前无训练权重的等权秩共识

将 DeepNano、PRODIGY pose 中位 pKd、负 FoldX interaction energy 转成 0–1 百分位秩后等权平均：

- n = 10；
- Spearman = 0.442；
- Pearson（秩共识对 pKd）= 0.704；
- 5 个有实验 Kd 的 parent-child 方向仅正确 3/5。

因此它可以作为临时 `affinity_evidence_score`，但仍不能作为 hard gate。

文件：

- `results/pvrig_positive11_structure_affinity_benchmark_20260719/provisional_equal_rank_affinity_consensus_positive10.tsv`
- `results/pvrig_positive11_structure_affinity_benchmark_20260719/provisional_equal_rank_affinity_consensus_metrics.json`

## 4. Rosetta 应如何使用

### 4.1 InterfaceAnalyzer

对每个复合物 pose 计算：

- `dG_separated`；
- `dG_separated/dSASAx100`；
- `dSASA_int`；
- `sc_value` 或 shape complementarity；
- `packstat`；
- `hbonds_int`；
- `delta_unsatHbonds`；
- `nres_int`；
- clash 和每残基界面能。

官方文档明确把它定位为界面分析器，并说明其不直接支持突变 binding ddG。`dG_separated` 是 Rosetta 能量差，不是实验 kcal/mol，也不是 Kd。

官方文档：<https://docs.rosettacommons.org/docs/latest/application_documentation/analysis/interface-analyzer>

推荐用途：

- 在相同 Docking 协议、相同受体构象、相同 pose 数量下比较候选；
- 评价 pose 是否有合理界面；
- 与 HADDOCK、PRODIGY、FoldX 做多方法共识。

不推荐用途：

- 直接输出“预测 Kd”；
- 将单个最低 Rosetta dG 当作最终亲和力；
- 在不同 pose 质量、不同受体和不同接口面积之间直接比较原始能量。

### 4.2 Flex ddG

Flex ddG 通过 Backrub 局部骨架采样、侧链重排和最小化，预测突变前后蛋白–蛋白结合能变化。论文报告它尤其适合多突变、小侧链到大侧链突变和抗体–抗原界面。

原始论文：<https://pmc.ncbi.nlm.nih.gov/articles/PMC5980710/>

2025 年 Graphinity 工作在更严格的抗体–抗原数据上报告：

- Flex ddG 与实验 ΔΔG 的 Pearson 约 0.46；
- FoldX 约 0.20；
- Flex ddG 明显更慢；
- 为生成训练数据，作者把 `nstruct` 从默认 35 降到 1。

来源：<https://www.nature.com/articles/s43588-025-00823-8>

推荐用途：

- 同 parent 的 sibling 重新排序；
- 同一固定参考 pose 上比较少量 CDR 突变；
- top 200–500 候选的高成本复排。

不推荐用途：

- 100 万或 15 万候选全量运行；
- 将两个完全不同 scaffold 的 Flex ddG 原值直接比较；
- 在未校准的错误 pose 上运行后宣称亲和力改善。

建议配置：

- pilot：每个突变 3–5 个独立重复；
- 正式：通过校准后对 top 候选增加到 15–35 个结构重复；
- 每个 parent 至少使用 2–3 个经验证参考 pose；
- 输出中位 ΔΔG、重复标准差、pose 间标准差和失败率。

### 4.3 SnugDock / RosettaDock

SnugDock 的主要任务是抗体–抗原 pose 优化，允许 paratope/CDR 和刚体取向共同调整；它不是直接的亲和力模型。

论文：<https://pmc.ncbi.nlm.nih.gov/articles/PMC2800046/>

对本课题的用途：

- 对 HADDOCK top pose 做独立局部重采样；
- 检查候选是否只有 HADDOCK 单一方法支持；
- 为 InterfaceAnalyzer 和 Flex ddG 生成 pose ensemble。

## 5. 新发现的其它方法

### 5.1 AlphaBind：优先测试

AlphaBind 是当前最值得补测的序列亲和力模型。它用抗体和抗原的 ESM-2nv embedding，预训练数据约 750 万条定量 AlphaSeq 测量，并包含 VHH72 优化案例。

论文：<https://pmc.ncbi.nlm.nih.gov/articles/PMC12296056/>

代码：<https://github.com/A-Alpha-Bio/alphabind>

本地代码与预训练 checkpoint：

- `downloaded_models/AlphaBind/`
- `downloaded_models/AlphaBind/alphabind/models/alphabind_pretrained_checkpoint.pt`

限制：

- 官方流程强烈建议先对目标或相关数据 fine-tune；
- PVRIG 没有训练亲和力数据，只能先做 zero-shot 校准；
- ESM-2nv 下载需要 NVIDIA NGC 凭据；
- 即使 zero-shot 在 10 个 PVRIG Kd 上有效，也只能先作为弱排序证据。

### 5.2 MVSF-AB 与 DLP-Affinity：第二优先级

代码已下载：

- `downloaded_models/MVSF-AB/`
- `downloaded_models/DLP-Affinity/`

MVSF-AB 是序列多视图亲和力模型；DLP-Affinity 同时报告 AB-Bind 和 sdAb 数据。当前仓库副本没有可直接确认的发布权重，因此先不加入生产流程。

论文：

- MVSF-AB：<https://pmc.ncbi.nlm.nih.gov/articles/PMC12089643/>
- DLP-Affinity：<https://pmc.ncbi.nlm.nih.gov/articles/PMC13070686/>

### 5.3 WAFFLE / AbRank：方向正确但部署重

AbRank 把问题直接定义为同抗原 affinity ranking，而不是强行回归统一 Kd，概念上更符合本课题。

代码：<https://github.com/biochunan/AbRank-WALLE-Affinity>

限制：

- 公开流程主要面向训练；
- 预计算图表示约 146 GB；
- 未确认有可直接用于 PVRIG 的发布 checkpoint；
- 暂不进入即时生产链。

### 5.4 Graphinity：不进入当前生产排序

Graphinity 论文自身发现：严格 CDR 同源隔离后性能明显下降；在预测复合物结构输入上 Pearson 仅约 0.02。现有 PVRIG 小基准也给出错误方向，因此不能作为当前亲和力主排序。

来源：<https://www.nature.com/articles/s43588-025-00823-8>

### 5.5 MM/GBSA 或 MM/PBSA：只用于很小的终选集

建议对 top 50–200 候选做：

1. 每个候选选取 2–3 个独立 pose；
2. 显式溶剂短程 MD；
3. 丢弃平衡前帧；
4. 对轨迹抽帧计算 MM/GBSA；
5. 报告 pose/重复的中位数和置信区间。

不做单帧 MM/GBSA，不把 MM/GBSA 数值换算成真实 Kd。该路线的主要用途是检查 Rosetta/FoldX 排序是否在短程动力学后仍稳定。

### 5.6 Boltz-2

Boltz-2 原始 affinity 模块主要针对蛋白–小分子；蛋白–蛋白亲和力仍需要额外 fine-tuning。因此当前不把原始 Boltz-2 affinity 输出用于 PVRIG VHH 排序。

官方论文与代码：

- <https://pmc.ncbi.nlm.nih.gov/articles/PMC12262699/>
- <https://github.com/jwohlwend/boltz>

### 5.7 AbBiBench / ProteinMPNN：文献上较好，但 PVRIG 只保留 family-local 诊断

AbBiBench 汇总了 9 个抗原体系、超过 15 万条有实验亲和力的抗体突变测量，并比较了 14 类模型。其关键结论不是“某个通用模型可直接输出 Kd”，而是：**在同一抗原、同一 parent 附近，结构条件 inverse-folding 模型的复合物 log-likelihood 往往比普通序列模型更适合做相对亲和力排序。**

论文：<https://arxiv.org/abs/2506.04235>

代码：<https://github.com/MSBMI-SAFE/AbBiBench>

本地已下载完整代码和 ProteinMPNN 权重：

- `downloaded_models/AbBiBench/`
- commit：`7d9c73e23c3c535fbb73ef073cf2fb9633e1fda8`

AbBiBench 公布的跨体系平均 Spearman 为：ProteinMPNN 0.30、ESM-IF1 0.28、AntiFold 0.21、FoldX 0.12、AF3 -0.02。这个结果说明 inverse-folding 值得测试，但不能证明它会迁移到 PVRIG。

已在 99 个冻结 HADDOCK pose 上完成 PVRIG 本靶点校准。VHH 链通过与哈希绑定阳性 FASTA 精确匹配识别，99/99 均为 A 链；没有再依赖链字母猜测。

| ProteinMPNN v_48_020 评分范围 | Spearman vs pKd | family 方向 | 决策 |
|---|---:|---:|---|
| 全 VHH | -0.067 | 3/6 | 不用于排序 |
| IMGT CDR1+2+3 | -0.115 | 5/6 | 仅同 parent 诊断 |
| IMGT CDR1+3 | -0.103 | 5/6 | 仅同 parent 诊断 |
| IMGT CDR3 | -0.018 | 4/6 | 不用于排序 |

因此，ProteinMPNN **没有通过跨 scaffold 全局亲和力排序门槛**。CDR1+2+3 和 CDR1+3 在 family 内方向较好，可作为同 parent sibling 的一个低权重 tie-breaker，但不能加入全局 `affinity_consensus`。

结果与复现脚本：

- `results/pvrig_positive11_proteinmpnn_affinity_pilot_20260722/`
- `scripts/benchmark_pvrig_proteinmpnn_affinity.py`
- `scripts/prepare_pvrig_proteinmpnn_cdr_positions.py`

后续若用于 family-local 诊断，保留以下列：

- `proteinmpnn_cdr123_loglik_rank_within_parent`；
- `proteinmpnn_cdr13_loglik_rank_within_parent`；
- 只对 CDR1/2/3，尤其 CDR3，计算给定 PVRIG 复合物结构后的条件 log-likelihood；
- 双受体、多个 pose 取中位数和保守最小值；
- 只作为同 parent 或近邻家族的排序证据，不跨 scaffold 解释为 Kd。

这一方法比 Flex ddG 快，但当前只能用于 family 内辅助，不得用于 5,000 个不同 scaffold 的全局亲和力主排序。

### 5.8 AbICL / AbLWR：排序思路先进，但暂不直接生产

2026 年的 AbICL 和 AbLWR 都把任务改写成 antigen-specific ranking，而不是统一回归绝对 Kd，方向上与 PVRIG 更匹配：

- AbICL 用少量同抗原已标注比较作为 in-context demonstrations；
- AbLWR 用 listwise ranking 和 positive-unlabeled 学习缓解标签稀疏。

来源：

- AbICL：<https://arxiv.org/abs/2607.05846>
- AbLWR：<https://arxiv.org/abs/2604.11272>

但它们目前过新，且未确认存在可直接复现实验的稳定权重/生产仓库。可列为后续研究分支，不替代眼下可校准的 Rosetta、PRODIGY、FoldX 和 inverse-folding 共识。

### 5.9 AbAffinity：不适合 PVRIG VHH

名为 AbAffinity 的 2026 模型公开权重主要针对 **scFv 与 SARS-CoV-2 HR2 特定肽**，输入还要求重链和轻链；它并不是通用 VHH–任意抗原亲和力模型。因此即使软件可运行，也不应把它的数值用于 PVRIG 排序。

代码：<https://github.com/ucrbioinfo/AbAffinity>

## 6. 推荐的亲和力排序定义

### 6.1 复合物层方法内汇总

对候选 `i`、受体构象 `r`、方法 `m`、pose `p`：

1. 先在相同受体、相同协议内把方法输出转为百分位秩；
2. 使用 top pose 的中位秩，而不是单个最优值；
3. 记录 pose dispersion；
4. 双受体使用保守汇总，避免只在 8X6B 或 9E6Y 单支表现好。

建议：

```text
method_score(i, r, m) = median(percentile_rank(score(i, r, m, top_poses)))
dual_method_score(i, m) = min(method_score(i, 8X6B, m), method_score(i, 9E6Y, m))
```

### 6.2 方法间共识

```text
affinity_consensus(i) = median(
    Rosetta_InterfaceAnalyzer_rank,
    PRODIGY_rank,
    FoldX_rank,
    validated_sequence_affinity_rank
)

affinity_uncertainty(i) =
    method_rank_IQR
  + pose_rank_dispersion
  + receptor_branch_disagreement
```

最终用于排序的亲和力证据：

```text
affinity_evidence_score = affinity_consensus - 0.25 * affinity_uncertainty
```

这只是候选优先级，不是 Kd。

### 6.3 同 parent 的 Flex ddG

Flex ddG 只在 parent 家族内排序：

```text
relative_affinity_score = -median(Flex_ddG_mutant_minus_parent)
relative_affinity_uncertainty = MAD_across_repeats_and_reference_poses
```

不同 parent 的 `relative_affinity_score` 不直接横向比较。

同 parent 内可以额外记录 ProteinMPNN CDR1+2+3 / CDR1+3 的 family percentile，但当前只作为低权重 tie-breaker；若与 Flex ddG、PRODIGY 的 family 方向冲突，则提高不确定性而不是强行平均。

## 7. 加入生产流程的验收门槛

### 序列 affinity 模型

与当前 DeepNano 基线比较，至少满足：

- 10 个已知 Kd 上 Spearman ≥ 0.45；
- known parent-child 方向 ≥ 4/5；
- leave-one-family-out 不由单一 family 驱动；
- disruptive mutant 测试方向正确率优于现有基线；
- 未通过时仅保留为 disagreement/acquisition 特征。

### Rosetta InterfaceAnalyzer

- 相同 99 pose 输入；
- 候选级 Spearman ≥ 0.45；
- family 方向 ≥ 4/5；
- 2–3 个 pose 汇总策略下排序稳定；
- 若与 pose 几何强相关但与 pKd 无提升，则只作为 pose-quality 特征。

### Flex ddG

- 5 个已知 parent-child Kd pair 中方向 ≥ 4/5；
- Spearman ≥ 0.50；
- 不同参考 pose 的方向一致率 ≥ 80%；
- 重复标准差不能大于 family 间主要差异；
- 未通过时不进入生产排序。

### MM/GBSA

- 只测试 top 小集；
- 至少 2 个 pose、3 个重复；
- 对已知 family pair 的方向优于随机；
- 只有在相对排序稳定且增加独立信息时才保留。

## 8. 与阻断评分的关系

亲和力和阻断样几何必须独立保存：

- `blocker_geometry_score`：回答是否占据/遮挡 PVRIG–PVRL2 功能界面；
- `affinity_evidence_score`：回答在给定复合物 pose 下是否具有较强结合证据；
- `developability_score`：回答是否有较低的表达、纯化、聚集等风险。

任何一个亲和力方法都不能把“能结合”自动解释为“能阻断”。最终应做多目标排序，而不是把三类标签混成一个训练标签。

## 9. 下一步执行顺序

1. 完成 150,000 条 TNP 结构可开发性筛选及哈希聚合；
2. 获得 Rosetta/PyRosetta 非商业许可并部署到 Node1；
3. 对现有 99 个冻结 pose 跑 InterfaceAnalyzer；
4. 对 5 个已知 parent-child pair 跑 Flex ddG pilot；
5. 已完成相同 99 pose 的 ProteinMPNN 全 VHH/CDR 校准：拒绝全局排序，仅保留 family-local 诊断；
6. 同时完成 AlphaBind zero-shot 依赖部署并测试 10 个已知 Kd；
7. 只有达到预注册门槛的方法才写入 `affinity_evidence_score`；
8. 对 top 5,000 Docking 复合物批量运行通过验证的快速方法；
9. 对 top 200–500 运行 Flex ddG；对 top 50–200 选择性运行 MM/GBSA。
