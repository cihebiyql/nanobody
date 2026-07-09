# PVRIG VHH Sequence-to-Blocker Workflow Robustness Plan

Updated: 2026-07-08

## Bottom line

这份文档定义当前 PVRIG VHH 从序列到 blocker-like 结构筛选流程的复核办法。目标不是再证明某个单一抗体，例如 HR-151，而是把流程变成可批处理、可回归、可发现漂移的筛选系统。

当前已完成的本地复核结果：

- 11 条 WO2021180205A1 成功阳性 VHH/HCVR 已完成结构预测、HADDOCK3 docking、8X6B/9E6Y 双基线评分与 consensus 汇总。
- 批次完整性检查通过：11/11 cases，109 consensus pose rows，A/A consensus=3，single-baseline A=36，plausible B=57，evidence-only E=13。
- 阈值敏感性网格已跑：11-positive 与 mutant/control panel 各 81 个参数组合；默认阈值分别复现锁定计数；两套网格均有 4/81 个设置保持 case-level call 完全不变。
- 新增 36 条 mutant/control panel：覆盖 PVRIG-20/30/38/39、20H5、30H2、39H4，不再只盯 151。
- 泄漏门控已跑：mutant panel 中 7 条 exact known-positive、29 条 near known-positive，作为阳性/近邻扰动控制，不允许进入“新设计候选”池。
- mutant/control panel 已完成 36/36 结构预测、36/36 HADDOCK3 docking、36/36 8X6B+9E6Y consensus；357 pose rows 中 A/A=8、single-baseline A=109、B=210、E=30。
- mutant/control panel 已完成分层统计：按 family、mutation class、leakage label、base molecule 汇总；12 条 CDR3 disruptive/alanine 且仍保留 A 信号的记录进入人工 pose review 队列。
- 新增 fast regression 已通过：classifier 边界、dual-baseline consensus 分支、批处理完整性、11-positive 与 mutant 阈值敏感性默认行、候选 scaffold、mutant leakage gate。

## Screening claim boundary

这个流程能给出的是：

```text
候选 VHH 的结构/对接姿态是否符合已成功 PVRIG blocker 案例学习出的 blocker-like 几何特征。
```

这个流程不能单独证明：

- 真实实验 IC50 或 Kd。
- Fc/NK/TIGIT/CD226 细胞层机制。
- 非 VHH 或复杂双抗格式的完整构象。
- 专利阳性或其近邻突变可以被当成新设计。

## Locked primary gate

默认 A-level VHH docking gate 仍使用 HR-151/成功案例校准值：

- `hotspot_overlap_count >= 14`
- `total_vhh_pvrl2_residue_pair_occlusion >= 500`
- `cdr3_pvrl2_residue_pair_occlusion >= 100`
- `cdr3_occlusion_fraction >= 0.15`
- `hotspot_overlap_count >= 14` 但 total occlusion `< 50` 必须降级为 `BINDER_LIKE_C`

Consensus 层：

- 两个基线都支持 A 且没有 C：`CONSENSUS_BLOCKER_LIKE_A`
- 单基线 A：`SINGLE_BASELINE_BLOCKER_RECHECK`
- A/C 或 B/C 冲突：必须 redock/manual inspection，不自动晋级。
- 只有 B：`BLOCKER_PLAUSIBLE_B`
- 只有 E：不进入 blocker 优先级。

## Robustness layers

### Layer 0: artifact integrity

脚本：`docking/success_case_validation/validate_batch_screening_outputs.py`

检查内容：

- 11 个 patent success workdir 是否都存在。
- FASTA、ambig table、HADDOCK cfg、node1 structure/haddock scripts 是否都存在。
- monomer raw PDB、chain A normalized PDB、HADDOCK run dir 是否都存在。
- 8X6B classification、9E6Y classification、8X6B+9E6Y consensus CSV 是否都存在。
- 汇总行数、家族覆盖、109 pose rows、锁定 aggregate counts 是否一致。
- 文档漂移作为 warning：旧 `batch_manifest.csv` 中 status 仍可能写 pending，但执行真值以 `batch_status.csv` 和实际文件为准。

命令：

```bash
python docking/success_case_validation/validate_batch_screening_outputs.py
```

本轮结果：PASS，warnings=22。warnings 来源是旧批次格式：11 个 manifest status pending 与 11 个逐例 cdr_ranges CSV 缺失；CDR 真值在批次级 `patent_success_validation_cdr_ranges.csv` 与 ambig table 中。

### Layer 1: classifier boundary regression

脚本：`docking/success_case_validation/test_blocker_screening_robustness.py`

锁定边界：

- hotspot 14 / total 500 / CDR3 100 / fraction 0.15 正好等于阈值时必须是 A。
- hotspot 13、total 499、CDR3 99、fraction 0.149 都不能是 A，只能降为 plausible B 或更低。
- hotspot 足够但 total 49 是 `BINDER_LIKE_C`。
- total 50 已越过 binder cutoff，不再算 C；若其他证据不足则是 E。

这保证 `>=` 与 `<` 的边界不会被未来修改误伤。

### Layer 2: dual-baseline consensus branch regression

脚本：`docking/success_case_validation/test_blocker_screening_robustness.py`

合成 CSV 覆盖所有重要分支：

- A/A -> `CONSENSUS_BLOCKER_LIKE_A`
- A/C -> `DISCORDANT_REDOCK_REQUIRED`
- B/C -> `DISCORDANT_PLAUSIBLE_VS_BINDER_RECHECK`
- C/C -> `CONSENSUS_BINDER_LIKE_C`
- B/B -> `BLOCKER_PLAUSIBLE_B`
- E/E -> `EVIDENCE_INFERENCE_ONLY_E`
- 单基线 A -> `SINGLE_BASELINE_BLOCKER_RECHECK`
- 单基线 C -> `SINGLE_BASELINE_BINDER_LIKE_C`

这避免只测 HR-151 单基线，导致 9E6Y/双基线逻辑漂移而无人发现。

### Layer 3: threshold sensitivity grids

脚本：

- `docking/success_case_validation/analyze_threshold_sensitivity.py`
- `docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py`

默认网格：

- hotspot: 12, 14, 16
- total occlusion: 400, 500, 600
- CDR3 occlusion: 75, 100, 125
- CDR3 fraction: 0.10, 0.15, 0.20

输出：

- `docking/calibration/patent_success_validation/threshold_sensitivity_summary.csv`
- `docking/calibration/patent_success_validation/THRESHOLD_SENSITIVITY_REPORT.md`
- `docking/calibration/mutant_validation_panel/mutant_panel_threshold_sensitivity_summary.csv`
- `docking/calibration/mutant_validation_panel/MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md`

解释：

- 11-positive 默认阈值行必须复现 109 rows、A/A=3、single-A=36、B=57、E=13。
- mutant/control 默认阈值行必须复现 357 rows、A/A=8、single-A=109、B=210、E=30。
- mutant/control grid 还锁定 retained-A disruptive/alanine controls：默认 any-A=12，consensus-A=3。
- 其他阈值不是生产阈值，只用来检查候选排序是否过度依赖某个临界值。
- 对阈值非常敏感的 A 只能作为 redock/re-score 对象，不能直接进入最终 blocker 优先级。

### Layer 4: mutant/control panel

脚本：`docking/success_case_validation/prepare_mutant_validation_batch.py`

默认 base VHH：

- PVRIG-20
- PVRIG-30
- PVRIG-38
- PVRIG-39
- 20H5
- 30H2
- 39H4

默认输出：

- `docking/calibration/mutant_validation_panel/mutant_panel.csv`
- `docking/calibration/mutant_validation_panel/mutant_panel.fasta`
- `docking/calibration/mutant_validation_panel/workdirs/*`
- `docking/calibration/mutant_validation_panel/run_all_node1_structure_predictions.sh`
- `docking/calibration/mutant_validation_panel/run_all_node1_haddock3.sh`
- `docking/calibration/mutant_validation_panel/postprocess_all_after_docking.sh`

面板组成：

- 7 条 unmutated positive/control leakage anchors。
- 7 条 single conservative CDR3 mutants。
- 7 条 single aromatic-to-alanine CDR3 mutants。
- 7 条 multi CDR3 alanine-scan mutants。
- 7 条 single conservative framework controls。
- 1 条 PVRIG-20 D103E patent-style CDR3 stability delta。

解释：

- unmutated base rows 用于确认阳性/泄漏门控，不是新候选。
- conservative CDR3 mutants 用于测试流程是否对小扰动过度脆弱。
- aromatic-to-alanine 和 CDR3 alanine scan 是负控/fragility controls；如果 docking 后仍强 A，需要人工检查是否 docking artifact。
- framework controls 用于检查 CDR range、scaffold、批处理路径是否稳定，而不是证明活性增强。

### Layer 5: sequence leakage gate

脚本：`docking/success_case_validation/check_vhh_sequence_leakage.py`

默认 reference：

- `机制/data/sequences/PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta`
- `positives/known_positive_antibodies.fasta`

标签：

- `EXACT_KNOWN_POSITIVE`: 不能进新候选排名，只能作为 positive/leakage control。
- `NEAR_KNOWN_POSITIVE`: 只能作为 mutant-validation/扰动控制，除非明确批准，否则不能当作新设计。
- `NO_CLOSE_KNOWN_POSITIVE`: 通过序列泄漏门，继续结构/docking/blocker workflow。

本轮 mutant panel 结果：

- candidates=36
- exact_known_positive=7
- near_known_positive=29
- 输出：`docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv`

### Layer 6: real node1 batch execution

本地脚本只能验证 scaffold、阈值、泄漏、postprocess 与回归逻辑。任何新序列或突变后序列的 blocker-like 结论必须真实执行：

1. NanoBodyBuilder2 structure prediction。
2. HADDOCK3 docking。
3. 8X6B baseline scoring。
4. 9E6Y baseline scoring。
5. consensus + leakage + threshold-sensitivity review。

本轮 mutant/control panel 已按同一链路完成全量执行：

- structure-ready records: 36/36
- structure QC sane: 36/36
- HADDOCK3 run dirs: 36/36
- 8X6B classification CSV: 36/36
- 9E6Y classification CSV: 36/36
- consensus CSV: 36/36
- aggregate consensus rows: 357
- labels: A/A=8, single-baseline A=109, plausible B=210, evidence E=30

关键脚本：

- `docking/success_case_validation/run_mutant_panel_batch.py`: resumable staged runner；structure 阶段顺序执行，docking/postprocess 可用 `--jobs` 并发。
- `docking/success_case_validation/summarize_mutant_panel_status.py`: 刷新每条记录完成度与 aggregate。
- `docking/success_case_validation/validate_mutant_panel_completion.py`: 锁定 36/36 完成、357 rows、A/A=8、single-A=109、B=210、E=30、exact=7、near=29。
- `docking/success_case_validation/summarize_mutant_panel_results.py`: 按 family/mutation_class/leakage/base 分层，并列出 CDR3 disruptive/alanine retained-A 人工复核队列。

### Layer 7: mutant/control stratified interpretation

脚本：`docking/success_case_validation/summarize_mutant_panel_results.py`

输出：

- `docking/calibration/mutant_validation_panel/MUTANT_PANEL_RESULT_STRATIFICATION.md`
- `docking/calibration/mutant_validation_panel/mutant_panel_result_stratification_summary.csv`

当前分层结论：

- family 层：20 family 109 rows，A/A=1，single-A=52；30 family 98 rows，A/A=6，single-A=26；38 family 50 rows，A/A=0，single-A=11；39 family 100 rows，A/A=1，single-A=20。
- mutation_class 层：`single_aromatic_to_alanine_cdr3` 保留 A/A=6、single-A=18；`multi_cdr3_alanine_scan` 保留 A/A=1、single-A=32。
- 人工复核队列：12 条 CDR3 disruptive/alanine rows 仍有 A/A 或 single-baseline A，不能自动解释为“突变后仍有真实 blocking”，必须看 pose、约束和 redock。
- 泄漏层：7 条 exact 与 29 条 near known-positive 全部只作为 validation/leakage controls，不进入新设计排序。

这层的作用是防止把 aggregate PASS 误读为生物学成功：它证明流程能批量处理、能暴露敏感/异常行，但不替代人工 pose inspection 或实验。

## Go / no-go criteria for production batch

### Local preflight must pass

```bash
python docking/success_case_validation/test_blocker_screening_robustness.py
python docking/success_case_validation/validate_batch_screening_outputs.py
python docking/success_case_validation/analyze_threshold_sensitivity.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
python docking/success_case_validation/check_vhh_sequence_leakage.py \
  --candidate-csv <candidate_panel.csv> \
  --out-csv <candidate_sequence_leakage.csv> \
  --fail-on-exact
```

No-go if：

- fast regression 失败。
- 默认阈值行无法复现锁定 aggregate counts。
- 候选池里出现 exact known-positive。
- 候选 ID/路径重复，或 scaffold 缺文件。

### Structural/docking batch must pass

每条候选必须有：

- input FASTA。
- CDR range source。
- normalized chain A monomer PDB。
- HADDOCK3 run directory。
- 8X6B classification CSV。
- 9E6Y classification CSV。
- multi-baseline consensus CSV。

No-go if：

- 只有单基线 A 就直接晋级。
- A/C 或 B/C discordant 未 redock/manual inspection。
- A 只在 permissive threshold 中出现，默认 gate 不支持。
- CDR3 alanine/aromatic negative controls 大量保留 A，提示 docking 约束或评分过拟合。

### Candidate promotion rules

优先级建议：

1. `CONSENSUS_BLOCKER_LIKE_A` + no leakage + pose passes manual inspection。
2. `SINGLE_BASELINE_BLOCKER_RECHECK` + default threshold robust + redock/second model supports。
3. `BLOCKER_PLAUSIBLE_B` only as follow-up，不作为主候选。
4. `BINDER_LIKE_C` and `EVIDENCE_INFERENCE_ONLY_E` 不作为 blocker 候选。

## Reproducible command set

```bash
# Existing successful calibration checks
python docking/success_case_validation/check_patent_success_calibration_status.py
python docking/success_case_validation/summarize_patent_success_calibration.py
python docking/success_case_validation/validate_patent_sequence_artifacts.py
python docking/success_case_validation/validate_success_case_standards.py
python docking/success_case_validation/test_success_case_workflow.py

# New robustness checks
python docking/success_case_validation/validate_batch_screening_outputs.py
python docking/success_case_validation/analyze_threshold_sensitivity.py
python docking/success_case_validation/prepare_mutant_validation_batch.py
python docking/success_case_validation/check_vhh_sequence_leakage.py \
  --candidate-csv docking/calibration/mutant_validation_panel/mutant_panel.csv \
  --out-csv docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv
python docking/success_case_validation/run_mutant_panel_batch.py --stage structure --keep-going
python docking/success_case_validation/run_mutant_panel_batch.py --stage docking --jobs 4 --keep-going
python docking/success_case_validation/run_mutant_panel_batch.py --stage postprocess --jobs 4 --keep-going
python docking/success_case_validation/summarize_mutant_panel_status.py
python docking/success_case_validation/validate_mutant_panel_completion.py
python docking/success_case_validation/summarize_mutant_panel_results.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
python docking/success_case_validation/test_blocker_screening_robustness.py
python3 -m py_compile docking/success_case_validation/*.py docking/scripts/*.py
```

## Current stop condition

本地复核层已经足够支持稳定批处理准备：规则边界可回归、双基线 consensus 可回归、11 个阳性 docking 产物可完整性验证、阈值敏感性可量化、突变/泄漏面板可批量生成并已完成全量 node1 结构/docking/postprocess。

下一步若要把这个流程用于新候选，必须用同一套 runner/validator 保持可复跑：先泄漏排除，再真实结构预测和 HADDOCK3，再双基线 consensus；不能把 mutant panel 的 near-positive 控制直接当新设计。

最终完成审计见：`docking/success_case_validation/WORKFLOW_COMPLETION_AUDIT.md`。

## 2026-07-08 mutant full-panel execution evidence

本轮已执行 mutant panel 的 36 条端到端全量任务。最早的 2 条 smoke 证明链路可跑通，随后全量批处理补齐所有记录。

完成度：

- records: 36/36
- structure ready: 36/36
- structure QC sane: 36/36
- HADDOCK3 run dirs: 36/36
- 8X6B/9E6Y consensus CSV: 36/36

Full-panel consensus 结果：

| panel | records | consensus rows | A/A | single-baseline A | plausible B | evidence E |
| --- | ---: | ---: | ---: | ---: | ---: |
| mutant/control panel | 36 | 357 | 8 | 109 | 210 | 30 |

状态汇总文件：

- `docking/calibration/mutant_validation_panel/mutant_panel_status.csv`
- `docking/calibration/mutant_validation_panel/MUTANT_PANEL_STATUS_SUMMARY.md`
- `docking/calibration/mutant_validation_panel/MUTANT_PANEL_COMPLETION_VALIDATION.md`
- `docking/calibration/mutant_validation_panel/MUTANT_PANEL_RESULT_STRATIFICATION.md`
- `docking/calibration/mutant_validation_panel/mutant_panel_result_stratification_summary.csv`
- `docking/calibration/mutant_validation_panel/MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md`
- `docking/calibration/mutant_validation_panel/mutant_panel_threshold_sensitivity_summary.csv`

解释：这证明 mutant panel 的真实 node1 结构预测、HADDOCK3、回传和本地双基线 postprocess 链路已经全量跑通。由于 36 条全部是 exact/near known-positive 控制或扰动，结果只能用于流程校准、泄漏门控和过拟合检测；不能作为新候选提交。
