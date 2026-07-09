# PVRIG blocker 最终校准层 v0

生成时间：2026-07-08  
输入来源：`/mnt/d/work/抗体/docking`  
输出目录：`model_data/`

## 结论

这批 WO2021180205A1 阳性 VHH/HCVR 和 mutant/control panel **应该接在模型最后校对层**，而不是混进普通训练集。

原因：

- 它们包含已知阳性/阻断案例，直接训练会造成泄漏。
- 它们有结构预测、HADDOCK3 docking、8X6B/9E6Y 双基线和 consensus，更适合校准 blocker-like 几何阈值。
- mutant/control panel 里 exact/near known-positive 很多，适合做 false-positive/鲁棒性/泄漏门控，而不是新候选正例。

## 生成的校准文件

| 文件 | 行数 | 用途 |
| --- | ---: | --- |
| `model_data/pvrig_blocker_positive_calibration_v0.csv` | 11 | 11 条已知阳性/阻断 VHH/HCVR，含 CDR、序列、IC50/Kd、case-level consensus |
| `model_data/pvrig_blocker_positive_pose_labels_v0.csv` | 109 | 阳性案例逐 pose consensus label，用于校准 docking/blocker 几何阈值 |
| `model_data/pvrig_blocker_mutant_control_calibration_v0.csv` | 36 | 36 条 mutant/control panel，含泄漏标签、突变类别和 consensus 统计 |
| `model_data/pvrig_blocker_mutant_pose_labels_v0.csv` | 357 | mutant/control 逐 pose label，用于鲁棒性与 false-positive 检查 |
| `model_data/pvrig_blocker_threshold_sensitivity_v0.csv` | 162 | positive + mutant 两套 81 阈值网格，共 162 行 |
| `model_data/pvrig_blocker_calibration_file_manifest_v0.csv` | 17 | 校准层引用的源文件清单 |
| `model_data/pvrig_blocker_calibration_summary_v0.json` | 1 | 聚合统计和集成规则 |

## 已锁定的聚合统计

- positive cases: 11
- positive pose rows: 109
- positive families: {"151": 3, "39": 3, "20": 2, "30": 2, "38": 1}
- mutant/control records: 36
- mutant/control pose rows: 357
- mutant leakage labels: {"NEAR_KNOWN_POSITIVE": 29, "EXACT_KNOWN_POSITIVE": 7}
- threshold sensitivity rows: 162

## 接入模型的方式

最终候选评分应该分两层：

```text
第一层：AI model prior
  - paratope probability
  - epitope probability
  - VHH-only/ranking score
  - PVRIG target epitope overlap

第二层：PVRIG blocker calibration gate
  - exact/near known-positive leakage exclusion
  - 8X6B + 9E6Y dual-baseline docking consensus
  - positive success threshold calibration
  - mutant/control false-positive audit
  - CDR3 disruptive/alanine retained-A manual review
```

推荐最终候选表新增列：

```text
ai_binding_rank_score
ai_paratope_confidence
ai_pvrig_epitope_overlap_top20
ai_pvrig_epitope_overlap_top50
known_positive_identity_fraction
leakage_label
haddock_8x6b_class
haddock_9e6y_class
dual_baseline_consensus_class
positive_threshold_supported
mutant_panel_false_positive_risk
manual_pose_review_required
final_blocker_like_calibrated_label
```

## 使用边界

- `pvrig_blocker_positive_calibration_v0.csv`：只能作为 positive calibration / threshold / leakage reference，不能当新设计候选。
- `pvrig_blocker_mutant_control_calibration_v0.csv`：只能作为 perturbation/control/leakage/false-positive audit，不能当新设计候选。
- 新候选如果 exact/near known-positive，必须从新候选排序中剔除，除非明确标为 control。
- 最终声明必须是 computational blocker-like geometry，不是实验 Kd/IC50 证明。
