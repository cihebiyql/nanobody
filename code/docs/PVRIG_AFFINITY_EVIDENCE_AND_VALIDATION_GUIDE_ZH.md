# PVRIG 亲和力证据分层与验证指南

## 1. 最重要的区分

当前流程中的“亲和力相关分数”实际上回答不同问题，不能直接混合：

1. **通用结合先验**：序列是否像会与抗原结合的 VHH。
2. **绝对结构能量分数**：给定 docking pose 是否有较好的物理接触。
3. **同亲本相对 ΔΔG**：在相同 parent pose 上，突变后可能变强还是变弱。
4. **blocker-like geometry**：VHH 是否占据 PVRIG-PVRL2 功能界面。
5. **实验 Kd**：结合平衡常数。
6. **实验 IC50**：竞争/阻断功能读出，不等于 Kd。

当前计算流程可以生成前四类证据，但不能将其写成后两类实验真值。

## 2. 每个分数应该怎么看

| 输出 | 数值方向 | 可以解释为 | 不能解释为 |
|---|---|---|---|
| `deepnano_binding_prior` | 越高越像 binder | 序列级弱结合先验 | Kd、IC50、阻断概率 |
| `nanobind_seq_binding_prior` | 越高越像 binder | 序列级弱结合先验 | Kd、IC50、阻断概率 |
| `binding_model_consensus` | 越高代表多模型共同偏高 | 弱共识特征 | 校准后的结合概率 |
| `binding_model_disagreement` | 越高说明模型意见越不一致 | 不确定性/主动学习特征 | 弱结合或强结合 |
| `nanobind_affinity_range` | 区间数值越小表面上越强 | 原始审计列 | PVRIG 的可信 Kd 区间 |
| `prodigy_pkd` | 越高表面上越强 | pose-dependent 连续弱先验 | 绝对 Kd |
| `foldx_interaction_energy` | 更负通常表面上更有利 | 同协议、同 pose 口径下的接口能量诊断 | 不同 docking pose 间的绝对亲和力 |
| `foldx_fixed_pose_ddg` | 负值表示 mutant 相对 parent 可能变强 | 同 parent 相对变化诊断 | 跨 scaffold 排名、实验 ΔΔG |
| `graphinity_ddg` | 负值表示单突变可能变强 | 单个界面突变诊断 | 8--20 个多突变 VHH 的直接亲和力 |
| `Rdual` / blocker geometry | 按冻结 docking 口径解释 | 阻断样几何教师分数 | Kd、真实阻断率 |

## 3. 当前已完成的验证结果

### 3.1 DeepNano / NanoBind 序列先验

11 条 PVRIG 阳性中 10 条有 Kd：

| 方法 | Spearman vs pKd | 同家族方向 | 当前处置 |
|---|---:|---:|---|
| DeepNano | 0.321 | 4/6 | 保留弱 prior |
| NanoBind-seq | -0.115 | 3/6 | 保留弱 prior/分歧特征 |
| 简单均值共识 | 0.091 | 3/6 | 不进入正式排名 |
| NanoBind-affi 区间中点 | 0.311 | 0/6（5 个平手） | 排除正式排名 |

36 条亲本/合成突变体压力测试中，DeepNano 和 NanoBind-seq 对多数预期破坏性 CDR3 突变给出了下降，但下降幅度小，且该面板没有实验标签。因此只能说它们具有弱的局部敏感性，不能称为已验证亲和力模型。

### 3.2 Phase 2 V3 target-conditioned binding prior

该模型的正式外部块为 `external_hTNFa`。V3 full 的 AUPRC 为 0.171535，基线 `esm2_pair` 为 0.225320，差值为 -0.053785，95% CI 为 [-0.072337, -0.038395]。正式决策为：

```text
FAIL_FALLBACK_TO_BASELINE
```

这说明新的 target-conditioned 模型没有超过预注册基线。可以保留 `esm2_pair` 作通用二分 binding prior，但这不是 PVRIG 亲和力、阻断或 Kd 真值。

### 3.3 PRODIGY / FoldX / Graphinity

11 条阳性的 99 个冻结 HADDOCK pose 实测：

| 方法 | 主要结果 | 当前处置 |
|---|---|---|
| PRODIGY pose 中位 | Spearman=0.310；pKd MAE=2.478；中位绝对误差约 427 倍 | 只作弱 pose prior |
| FoldX absolute interaction | Spearman=0.236 | 不做跨候选亲和力排名 |
| FoldX fixed-pose multi-mutant ΔΔG | 5 个已知 pair 中方向 2/5，MAE=1.103 kcal/mol | 只作同 parent 诊断 |
| Graphinity additive approximation | 4 个可评估 pair 中方向 1/4；仅覆盖 9/79 个突变 | 排除当前正式排名 |

## 4. 验证亲和力模型的正确层级

### Level 0：运行与复现性

必须保存：

- 模型、权重、输入序列、PDB 和协议版本的 hash；
- 单位、链定义、温度、pH 和聚合状态；
- 所有 pose/repeat 的原始结果；
- 失败原因。技术失败必须为 NA，不能当作低分或阴性。

### Level 1：已知阳性内部排序

用已知 Kd 计算：

- `pKd = -log10(Kd[M])`；
- Pearson、Spearman；
- pKd MAE；
- 同 parent 的方向正确率。

这一层只能验证“阳性中谁可能更强”，不能验证 binder/non-binder 区分。

### Level 2：binder / non-binder 富集

需要与阳性匹配的阴性：

- 同 scaffold 的实验失活突变；
- 表达正常但不结合 PVRIG 的 VHH；
- 结合 PVRIG 但不阻断的 hard negative；
- 非相关抗原 VHH 仅作辅助 easy negative。

评估 AUROC、AUPR、EF1%、top-k recall、Brier score 和校准曲线。阴性构造不当会让 AUROC 虚高，因此 AUPR 和 hard-negative 表现更重要。

### Level 3：同 parent 成对 ΔΔG

对有实验 Kd 的 parent/child 计算：

```text
ΔΔG_exp = RT ln(Kd_child / Kd_parent)
```

要求：

- parent 和 child 共用同一复合物姿势/受体构象；
- 至少 5 个独立 side-chain/repack repeat；
- 报告 median、MAD/SD、方向正确率和 MAE；
- 将“界面内突变”和“界面外突变”分开；
- Graphinity 这类单点模型不能默认对多突变结果相加。

### Level 4：外部泛化

数据必须按以下单位 group split，不能随机拆 sibling rows：

- parent/framework cluster；
- CDR3 cluster；
- 生成方法和 campaign；
- antigen/target；
- 近邻序列家族。

正式 test 必须在阈值冻结后一次性 unseal。置信区间应按 candidate/family bootstrap，不能将同一候选的 9 个 pose 当成 9 个独立样本。

### Level 5：pose 和物理稳定性

对进入结构亲和力评估的候选，必须检查：

- 8X6B/9E6Y 受体构象间结论是否一致；
- docking seed/pose 之间的方差；
- 是否存在 N 端、断链、clash 或虚假接触；
- 关键界面残基和氢键是否在 pose ensemble 中稳定；
- 简单 minimized/repacked 后排名是否稳定；
- 对小面板可进一步做 Flex-ddG 或短 MD + MM/GBSA。

## 5. 项目内建议验收门槛

下列是项目建议门槛，不是通用学术定律。

### 只作弱 prior

- 外部 hard-negative AUPR 明显高于 prevalence；
- top 1%/5% 富集高于随机；
- bootstrap 95% CI 的性能增益下界 > 0；
- 不设单模型 hard fail。

### 成为正式亲和力排序特征

- 冻结外部集 Spearman 建议至少 0.4--0.5；
- 同 parent ΔΔG 方向正确率建议至少 70%；
- ΔΔG MAE 建议 < 1 kcal/mol；
- 结果对 pose/receptor/seed 不能高度敏感；
- 多 seed 间性能增益一致，且下置信界 > 0。

### 声称“预测 Kd”

除了相关性，还必须有：

- 已知 Kd 外部校准集；
- 对 pKd 的 MAE、RMSE、校准斜率和截距；
- 不同 Kd 区间、家族和 assay 类型的分层误差；
- 至少达到 pKd MAE <= 1（仍约为 10 倍误差）才值得作粗糙 Kd 范围使用。

当前 PRODIGY pKd MAE=2.478，明显不满足该条件。

### 成为 hard gate

除了上述条件，还需：

- 已知强阳性的 false-negative rate 可控；
- 保留多样性和新 parent，不能只保留某一生成器风格；
- 有 rescue 通道：高不确定、高 blocker geometry 或新 scaffold 不得因单个亲和力分数被删除。

当前没有任何亲和力方法达到 hard-gate 条件。

## 6. 当前流程应如何组合

### 50 万条序列级前筛

- DeepNano、NanoBind-seq、`esm2_pair` 可以作快速连续特征；
- 保留多模型分歧和不确定性；
- 不应因任一模型低分直接删除候选；
- NanoBind-affi 区间只保留审计，不进入排名。

### 结构预测后

- blocker-like geometry 是当前主要计算教师信号；
- PRODIGY 仅作弱的 pose prior；
- FoldX interaction 只作同口径 pose 诊断；
- 对同 parent 少数重要变体，可补做 fixed-pose FoldX ΔΔG。

### 最终多目标选择

亲和力相关特征、blocker geometry、developability、expression/purity 应保持独立列。在校准之前优先使用 Pareto 选择、分层抽样和主动学习，不要用一个看似精确的加权总分掩盖各路证据的不确定性。

## 7. 当前结论

1. DeepNano、NanoBind-seq 和 `esm2_pair` 是 weak binding priors，不是亲和力真值。
2. NanoBind-affi 在 PVRIG 阳性上区分度不足，不参与正式排名。
3. PRODIGY 有弱方向信号，但绝对 Kd 偏差很大。
4. FoldX 相对 ΔΔG 只在少数家族上有效，需要先解决 pose 校准。
5. Graphinity 当前不适合多突变 VHH 排名。
6. 当前亲和力部分不设 hard gate，不覆盖 docking blocker-like geometry。

## 8. 主要证据文件

- `results/pvrig_positive11_binding_prior_20260719/POSITIVE11_BINDING_PRIOR_EVALUATION_ZH.md`
- `results/pvrig_mutant36_binding_prior_20260719/MUTANT36_BINDING_PRIOR_SENSITIVITY_ZH.md`
- `results/pvrig_positive11_structure_affinity_benchmark_20260719/PVRIG_POSITIVE_AFFINITY_METHOD_BENCHMARK_ZH.md`
- `/mnt/d/work/抗体/data/experiments/phase2_5080_v1/audits/phase2_v3_preregistration.json`
- `/mnt/d/work/抗体/data/experiments/phase2_5080_v1/runs/phase2_v3_binding/phase2_v3_binding_20260712T024039_011095Z/formal_evaluation/formal_evaluation_summary.json`
