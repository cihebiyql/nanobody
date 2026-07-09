# PVRIG 11 阳性 VHH 的 QC 指标范围与筛选门控稳健性

Updated: 2026-07-08

## 结论先说

有范围，但不能把所有范围都变成 hard gate。现在证据支持把筛选标准分成三层：

1. **稳定 hard gate**：输入合规、标准氨基酸、IMGT/Kabat/ANARCI 编号完整、heavy variable domain、完整 FR/CDR、阳性 CDR 泄漏排除。
2. **开发性 warn/ranking**：FR2/VHH-like、AbNatiV、Sapiens、人源化负担、pI/charge/GRAVY、TNP、Cys/糖基化/脱酰胺/异构化/疏水 run。
3. **阻断生物学 gate**：不能由这些序列 QC 指标替代，仍必须走 DeepNano binder 预筛 + 结构预测 + PVRIG/PVRL2 competition docking/occlusion + 多 baseline consensus。

最重要的校准发现是：11 条已知 PVRIG blocker 中，6/11 被 L2 判为 `REJECT_NOT_VHH_LIKE` 或 poor single-domain suitability，2/11 在 all-11 TNP 中出现 PNC red。因此 FR2/VHH-like 或 TNP 单项红旗不能作为“没有阻断作用”的 hard fail，只能作为提交风险/可开发性风险。

## 输入与复跑证据

- 阳性 FASTA：`/mnt/d/work/抗体/reports/qc_positive_metric_ranges/pvrig_11_success_positives.fasta`，11 条。
- node1 QC 输出：`/mnt/d/work/抗体/reports/qc_positive_metric_ranges/node1_pvrig_11_positive_qc`。
- node1 主命令：`/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc ... --local-positive-cdr-csv ... --top-n 20 --reserve-n 10`。
- all-11 TNP 补跑：安全 header FASTA `pvrig_11_success_positives_tnp_safe.fasta`，输出 `tnp_safe_all11/TNP_Results_Multientry.json`。
- 机器可读范围表：`/mnt/d/work/抗体/reports/qc_positive_metric_ranges/pvrig_positive_qc_metric_ranges.csv`。
- 每条阳性明细：`/mnt/d/work/抗体/reports/qc_positive_metric_ranges/pvrig_positive_qc_per_sequence_metrics.csv`。

## 阳性集核心范围

- VHH length: 120 - 127 (median 121, n=11, missing=0)
- IMGT CDR1 length: 8 - 10 (median 8, n=11, missing=0)
- IMGT CDR2 length: 7 - 8 (median 7, n=11, missing=0)
- IMGT CDR3 length: 14 - 19 (median 15, n=11, missing=0)
- FR2 hallmark score: 0.25 - 1 (median 0.75, n=11, missing=0)
- AbNatiV VHH score: 0.7523 - 0.8585 (median 0.799, n=9, missing=2)
- AbNatiV FR-VHH score: 0.8697 - 0.9759 (median 0.8966, n=9, missing=2)
- Sapiens mean self probability: 0.6683 - 0.78 (median 0.7267, n=11, missing=0)
- Sapiens suggested mutations: 11 - 25 (median 15, n=11, missing=0)
- pI: 4.995 - 8.62 (median 5.708, n=11, missing=0)
- net charge pH 7.4: -5.336 - 1.484 (median -1.447, n=11, missing=0)
- GRAVY: -0.4959 - -0.0614 (median -0.2512, n=11, missing=0)
- instability index: 35.029 - 39.172 (median 37.136, n=11, missing=0)
- Cys count: 2 - 4 (median 4, n=11, missing=0)
- deamidation NG/NS/NT count: 0 - 2 (median 2, n=11, missing=0)
- isomerization DG/DS/DD/DT count: 2 - 5 (median 3, n=11, missing=0)
- 5-mer hydrophobic run count: 0 - 1 (median 0, n=11, missing=0)
- TNP total CDR length: 29 - 36 (median 30, n=11, missing=0)
- TNP CDR3 length: 14 - 19 (median 15, n=11, missing=0)
- TNP CDR3 compactness: 1.0119 - 1.4501 (median 1.0688, n=11, missing=0)
- TNP PSH: 83.8441 - 125.1016 (median 104.1461, n=11, missing=0)
- TNP PPC: 0 - 0.3038 (median 0.1131, n=11, missing=0)
- TNP PNC: 0 - 3.0326 (median 0.1326, n=11, missing=0)

## 门控稳健性复核

### 可以稳定 hard gate

- L1 编号完整性：PASS=11。11/11 阳性都能编号，因此新候选无法编号、无法识别重链 variable domain、FR/CDR 不完整时可以 hard fail。
- CDR 泄漏排除：`identity_threshold=0.8`，`safe_identity_threshold=0.75`；`pass_similarity_filter` 为 FAIL=11；阳性 `max_CDR_identity_to_positive` 为 1 - 1 (median 1, n=11, missing=0)。新候选任一 CDR 对阳性参照 identity >=0.80 应 hard fail，0.75-0.80 应边界预警。
- 官方 validator 失败原因：45 条，全为 {'high_cdr_identity': 45}；CDR 分布 {'CDRH1': 13, 'CDRH2': 16, 'CDRH3': 16}；identity 范围 0.8667-1。这证明阳性/近阳性会被泄漏门控稳定抓住。
- 标准 20 AA、单条 VHH、长度粗范围仍可 hard gate；但不要把本批阳性的 120-127 aa 当唯一硬阈值，建议继续保留工具里的宽范围 95-160 aa，并把 105/110-145 aa 或 120-127 aa 附近作为偏好区间。

### 只能 warn/ranking，不能当 blocker hard fail

- VHH-like/FR2：L2 结果为 FAIL=6; PASS=4; WARN=1，single-domain suitability 为 poor=6; good=5，FR2 hallmark score 为 0.25 - 1 (median 0.75, n=11, missing=0)。已知阳性里有大量 L2 fail/poor，因此它只能提示单域性、表达和聚集风险。
- AbNatiV：VHH score 为 0.7523 - 0.8585 (median 0.799, n=9, missing=2)，FR-VHH score 为 0.8697 - 0.9759 (median 0.8966, n=9, missing=2)；2/11 缺值。现有 <0.55 fail、0.55-0.70 warn 的工具阈值可用于自然性风险，但缺值或偏低不能直接判定无阻断。
- Sapiens：mean self probability 为 0.6683 - 0.78 (median 0.7267, n=11, missing=0)，建议突变数为 11 - 25 (median 15, n=11, missing=0)。它评估人源化负担，不评估 PVRIG/PVRL2 阻断。
- 理化性质：pI 为 4.995 - 8.62 (median 5.708, n=11, missing=0)，charge 为 -5.336 - 1.484 (median -1.447, n=11, missing=0)，GRAVY 为 -0.4959 - -0.0614 (median -0.2512, n=11, missing=0)。这些可用于表达/纯化/非特异风险排序，但 PVRIG 阳性允许较宽范围。
- Cys 和责任位点：Cys count 为 2 - 4 (median 4, n=11, missing=0)，N-glyc motif 为 0 - 0 (median 0, n=11, missing=0)，deamidation 为 0 - 2 (median 2, n=11, missing=0)，isomerization 为 2 - 5 (median 3, n=11, missing=0)，hydrophobic 5-run 为 0 - 1 (median 0, n=11, missing=0)。非经典 Cys、异构化 motif、疏水 run 在阳性里也存在，所以必须位置/结构复核。
- TNP：L/L3/C/PSH/PPC flags 全绿，PNC flags 为 green=9; red=2；PNC red 阳性为 PVRIG-20, 20H5。PNC red 是开发性风险，不是阻断否决。

### 本次 QC 没覆盖或不能替代的指标

- `structure_tools` 配置为 ``，L4 结果为 SKIPPED=7; NOT_RUN=4；IgFold/NanoNet/NanoBodyBuilder2 coverage、FR RMSD、CDR3 anchor distance 在本次 QC 中为空。
- `blocker_class`、PVRIG interface contact score、PVRL2 competition score 在本次 QC 中未自动运行；若 TSV 中出现 50.00，那是中性占位，不是 docking 证据。
- DeepNano 只能作为 sequence-only / prompt-site binder 预筛；它不判断是否阻断 PVRIG-PVRL2。
- 实验 Kd/IC50/cell assay 不在本 QC 输出中；只能从专利/文献表单独追溯。

## 推荐的批处理筛选标准

1. **先硬门控**：标准 20 AA、单条序列、长度宽范围、ANARCI/AbNumber 编号成功、完整 FR/CDR、heavy chain、CDR 泄漏排除。
2. **再 binder/阻断门控**：DeepNano 只做 binder 预筛；真正 blocker 必须导入结构预测 + 8X6B/9E6Y 或等价 PVRL2 competition docking/occlusion summary。
3. **再可开发性分层**：FR2/VHH-like、AbNatiV、Sapiens、TNP、pI/charge/GRAVY、Cys/N-glyc/疏水 run 进入 warn/ranking；只有多项严重异常叠加或位于 CDR/暴露区域时才人工 hard fail。
4. **最后组合多样性**：team diversity/cluster limit 只在候选已经过硬门控后用于 top-N 组合，不用于判断单条是否 blocker。

## 稳健性结论

- 对批处理来说已经足够稳健的部分：编号完整性、阳性泄漏排除、基础序列合规、粗长度范围、机器可读汇总。
- 需要保持柔性的部分：VHH-like/FR2、AbNatiV、TNP、Sapiens、理化和责任位点。阳性结果本身证明这些不能单独 hard fail blocker。
- 仍需外部流程提供证据的部分：结构稳定性交叉验证、复合物 docking、PVRIG/PVRL2 阻断几何、实验 Kd/IC50。
- 因为当前阳性数只有 11 条，阳性范围应作为校准 envelope 和异常检测，而不是窄硬阈值；真正 hard gate 必须只放在能被阳性集和工具目标共同支持的项目上。

## 工具缺口记录

- all-11 TNP 数值已补齐，但 TNP 在 `--web`/单条后处理日志里仍出现 `Failed to process output PDB` 的非致命错误；本报告采用 `TNP_Results_Multientry.json` 的数值和 flag，不把空的单条 liability JSON 当完整结构 liability 证据。
- `vhh-competition-qc` 当前不会自动跑新候选 HADDOCK/blocking；必须先单独跑复合物流程，再把 docking summary 导入 QC。

## Reference counts

- official positive CDRs: 48
- local positive CDRs: 30
- portfolio count: 11
- TNP all-11 records: 11

