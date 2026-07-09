# PVRIG VHH Screening Workflow Completion Audit

Updated: 2026-07-08

## Verdict

当前 PVRIG VHH 从序列到 blocker-like 结构筛选流程已经完成一轮可复跑验证：

- 11 条 WO2021180205A1 阳性 VHH/HCVR 已完成结构预测、HADDOCK3 docking、8X6B/9E6Y 双基线评分和 consensus。
- 36 条 mutant/control panel 已完成结构预测、HADDOCK3 docking、8X6B/9E6Y 双基线评分、completion validation、分层统计和阈值敏感性审计。
- fast regression 覆盖 classifier 边界、dual-baseline consensus 分支、patent batch integrity、11-positive threshold grid、mutant threshold grid、candidate scaffold 和 mutant leakage gate。
- 结果边界已写清楚：这些输出是 computational prioritization，不是实验 IC50/Kd 或细胞阻断证明；exact/near known-positive 只能作校准/泄漏/扰动控制。

## Requirement-to-evidence audit

| Requirement | Current evidence | Status |
| --- | --- | --- |
| 不只验证 HR-151，要覆盖其他成功 VHH | `docking/calibration/patent_success_validation/PATENT_SUCCESS_SERIES_POSTPROCESS_SUMMARY.md`：11/11 positives，family 20/30/38/39/151；20H5 有 3 个 A/A poses | PASS |
| 正例序列和 CDR 不能混用错误编号 | `validate_patent_sequence_artifacts.py` locks FASTA=30, mapping=30, raw ANARCI=30, success series=11, raw CDR3 exact FASTA matches=30；legacy summary-vs-raw CDR3 mismatch fixed as audit warning | PASS |
| 要能从一条 VHH 序列生成结构/docking 工作目录 | `prepare_candidate_sequence_workflow.py` generates FASTA, CDR ranges, node1 structure script, HADDOCK3 config, restraint table and postprocess script；fast regression runs this in a temp dir | PASS |
| 要有真实结构预测和 docking 批处理验证 | patent 11/11 and mutant 36/36 have monomer chain-A PDBs, HADDOCK run dirs, 8X6B/9E6Y classifications and consensus CSVs | PASS |
| 要验证突变/换氨基酸后的流程稳定性 | `docking/calibration/mutant_validation_panel/MUTANT_PANEL_COMPLETION_VALIDATION.md` locks 36 rows, 357 consensus rows, A/A=8, single-A=109, B=210, E=30 | PASS |
| 要识别突变负控高分异常，而不是误解成真实阻断 | `MUTANT_PANEL_RESULT_STRATIFICATION.md` flags 12 CDR3 disruptive/alanine retained-A rows for manual pose review | PASS |
| 要测试不同参数/阈值 | `THRESHOLD_SENSITIVITY_REPORT.md` and `MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md` each test 81 settings and lock default aggregate counts | PASS |
| 要有泄漏排除 | `mutant_panel_sequence_leakage.csv` and `validate_mutant_panel_completion.py` lock exact=7, near=29 for control panel; production docs require exact/near exclusion from new-candidate ranking | PASS |
| 要能批处理、可恢复、可复核 | `run_mutant_panel_batch.py` is staged/resumable; `summarize_mutant_panel_status.py`, `validate_mutant_panel_completion.py`, `summarize_mutant_panel_results.py`, and threshold scripts regenerate status/report artifacts | PASS |
| 要有自动回归 | `test_success_case_workflow.py`, `test_blocker_screening_robustness.py`, `validate_success_case_standards.py`, and compile checks passed in the final run | PASS |

## Locked aggregate evidence

### Patent success calibration

- Cases: 11
- Families: 151=3, 20=2, 30=2, 38=1, 39=3
- Consensus rows: 109
- Labels: A/A=3, single-baseline A=36, plausible B=57, evidence E=13
- Threshold grid: 81 settings; default row reproduces locked counts; 4/81 settings preserve case-level calls

### Mutant/control panel

- Records: 36
- Structure-ready: 36/36
- HADDOCK3 run dirs: 36/36
- Consensus CSVs: 36/36
- Consensus rows: 357
- Labels: A/A=8, single-baseline A=109, plausible B=210, evidence E=30
- Leakage: exact known-positive=7, near known-positive=29
- Manual review queue: 12 CDR3 disruptive/alanine retained-A rows
- Threshold grid: 81 settings; default row reproduces locked counts; 4/81 settings preserve case-level calls; default disruptive any-A=12

## Production use rule

For a new VHH sequence, use this order:

```text
sequence
  -> ANARCI/manual CDR range
  -> leakage check
  -> NanoBodyBuilder2 structure prediction on node1
  -> HADDOCK3 docking
  -> 8X6B classification
  -> 9E6Y classification
  -> multi-baseline consensus
  -> threshold sensitivity / manual pose review
  -> blocker-like prioritization label
```

Promotion is allowed only when:

- The candidate is not exact/near known-positive unless it is explicitly a control.
- The default gate, not only permissive thresholds, supports the label.
- Dual-baseline A/A is preferred; single-baseline A remains recheck.
- CDR3 disruptive/alanine-like retained-A behavior triggers manual pose inspection.
- The final claim is phrased as computational blocker-like geometry, not experimental blocking proof.

## Final verification command set

This command set passed on 2026-07-08:

```bash
python docking/success_case_validation/check_patent_success_calibration_status.py
python docking/success_case_validation/summarize_patent_success_calibration.py
python docking/success_case_validation/validate_patent_sequence_artifacts.py
python docking/success_case_validation/validate_success_case_standards.py
python docking/success_case_validation/test_success_case_workflow.py
python docking/success_case_validation/test_blocker_screening_robustness.py
python docking/success_case_validation/validate_batch_screening_outputs.py
python docking/success_case_validation/analyze_threshold_sensitivity.py
python docking/success_case_validation/summarize_mutant_panel_status.py
python docking/success_case_validation/validate_mutant_panel_completion.py
python docking/success_case_validation/summarize_mutant_panel_results.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
python3 -m py_compile docking/success_case_validation/*.py docking/scripts/*.py
```

Final observed marker:

```text
FULL_REGRESSION_WITH_MUTANT_THRESHOLD_PASSED
```

