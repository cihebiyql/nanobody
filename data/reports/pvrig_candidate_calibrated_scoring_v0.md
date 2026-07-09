# PVRIG 候选 VHH：AI prior + 最终校准层批量打分 v0

生成时间：2026-07-08  
脚本：`scripts/score_pvrig_candidates_with_calibration.py`

## 目的

这个脚本把前面两部分串起来：

```text
Phase 1 AI prior
  - VHH paratope probability
  - PVRIG epitope probability
  - VHH-only score
  - PVRIG target overlap

Final calibration gate
  - known-positive leakage check
  - optional 8X6B/9E6Y consensus class
  - optional numeric docking blocker gate
  - final calibrated label
```

重要边界：如果没有 docking/consensus 字段，脚本不会把候选直接叫做 blocker，只会输出 `*_NEEDS_DOCKING_CALIBRATION`。

## 输入格式

支持 CSV 或 FASTA。

CSV 推荐列：

```text
candidate_id
vhh_seq             # 或 sequence/seq/aa_sequence
cdr1                # 可选
cdr2                # 可选
cdr3                # 可选
```

如果已经有 docking 后处理结果，也可以额外提供：

```text
dual_baseline_consensus_class
haddock_8x6b_class
haddock_9e6y_class
hotspot_overlap_count
total_vhh_pvrl2_residue_pair_occlusion
cdr3_pvrl2_residue_pair_occlusion
cdr3_occlusion_fraction
```

## 输出重点列

```text
ai_vhh_score_raw
ai_pvrig_target_hits_top20
ai_pvrig_target_recall_top20
ai_pvrig_target_hits_top50
ai_pvrig_target_recall_top50
ai_prior_label
known_positive_identity_fraction
max_cdr_identity_to_known_positive
leakage_label
provided_or_inferred_consensus_class
numeric_docking_class
final_blocker_like_calibrated_label
manual_pose_review_required
recommended_next_step
```

## 使用示例

```bash
./scripts/score_pvrig_candidates_with_calibration.py \
  --candidates my_candidates.csv \
  --out reports/my_candidates_calibrated.csv \
  --top-k 20
```

默认使用：

- `models/phase1_sequence_baseline/`
- `model_data/pvrig_target_sequence_v0.fasta`
- `model_data/pvrig_full_sequence_mask_v0.csv`
- `model_data/pvrig_blocker_positive_calibration_v0.csv`
- `/mnt/d/work/抗体/positives/known_positive_antibodies.fasta`

## Smoke test

输入：`reports/phase1_calibrated_smoke_candidates.csv`  
输出：`reports/phase1_calibrated_smoke_results.csv`

| candidate | 目的 | 结果 |
| --- | --- | --- |
| `smoke_exact_HR151` | 已知阳性 exact leakage | `EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL` |
| `smoke_near_mutant` | 近邻 known-positive mutant | `HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW` |
| `smoke_zym_no_docking` | 非泄漏、无 docking | `AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION` |
| `smoke_zym_with_consensus_A` | 非泄漏、提供 A/A consensus | `CALIBRATED_BLOCKER_LIKE_A` |

这四类结果说明门控路径已经跑通：

```text
known positive -> exclude
near positive -> hold/manual leakage review
AI-only candidate -> needs docking calibration
AI + consensus A -> calibrated blocker-like A
```

## 校准规则

当前脚本内置与 `blocker_judgment_rules_v2.json` 一致的 VHH docking A-level gate：

```text
hotspot_overlap_count >= 14
total_vhh_pvrl2_residue_pair_occlusion >= 500
cdr3_pvrl2_residue_pair_occlusion >= 100
cdr3_occlusion_fraction >= 0.15
```

以及 binder-like 降级：

```text
hotspot_overlap_count >= 14 且 total occlusion < 50
  -> BINDER_LIKE_C
```

## 解释

这个脚本现在可以作为最终候选表的统一入口。后续如果候选已经完成 HADDOCK3/8X6B/9E6Y 后处理，只要把 consensus/classification 字段并入候选 CSV，脚本就会输出 calibrated label；如果还没有 docking，它只会给 AI prior 和下一步建议。
