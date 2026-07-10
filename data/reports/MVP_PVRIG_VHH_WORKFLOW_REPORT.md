# PVRIG-VHH 结合/阻断预测 MVP 报告

Updated: 2026-07-09

## MVP 结论

本 MVP 已把当前本地数据链路串起来：VHH 候选池 -> Phase 1 序列/表位先验模型 -> PVRIG 已知阳性与突变控制校准 -> 泄漏排除 -> Top 新候选排序。

重要边界：没有提供 docking consensus 的新候选不会被宣称为真实 blocker，只能标记为 `*_NEEDS_DOCKING_CALIBRATION`。已知 PVRIG 阳性/阻断 VHH 只作为控制和校准，不进入新候选排名。

## 输入与产物

| 类型 | 路径 |
| --- | --- |
| MVP 候选池 | `/mnt/d/work/抗体/data/model_data/mvp_candidates_v0.csv` |
| 全量打分表 | `/mnt/d/work/抗体/data/reports/mvp_pvrig_candidate_scores_v0.csv` |
| Top 新候选 | `/mnt/d/work/抗体/data/reports/mvp_pvrig_top_candidates_v0.csv` |
| 控制组结果 | `/mnt/d/work/抗体/data/reports/mvp_pvrig_control_scores_v0.csv` |
| 结构 contact MVP | `/mnt/d/work/抗体/data/model_data/sabdab2_single_domain_contacts_mvp.csv` |
| 结构 contact 报告 | `/mnt/d/work/抗体/data/reports/sabdab2_contact_extraction_mvp.md` |
| 运行摘要 | `/mnt/d/work/抗体/data/reports/mvp_pvrig_summary_v0.json` |

## 数据规模

| 项目 | 数量 |
| --- | ---: |
| 候选池总行数 | 547 |
| 新候选输入行数 | 500 |
| Top 输出行数 | 50 |
| 控制组行数 | 47 |

候选角色分布：

```json
{
  "known_pvrig_blocking_positive_control_not_ranked": 11,
  "mutant_or_leakage_control_not_ranked": 36,
  "new_candidate_from_zym_vhh_affinity_seq_test": 500
}
```

最终标签分布：

```json
{
  "AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION": 500,
  "EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL": 18,
  "HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW": 29
}
```

泄漏标签分布：

```json
{
  "EXACT_KNOWN_POSITIVE": 18,
  "NEAR_KNOWN_POSITIVE_OR_CDR_SIMILAR": 29,
  "NO_KNOWN_POSITIVE_LEAKAGE": 500
}
```

## Phase 1 小模型资产

本 MVP 复用已经训练好的纯 NumPy baseline，不依赖 PyTorch/sklearn。它包含 VHH paratope residue head、PVRIG/antigen epitope residue head 和 VHH score ridge head。指标只能说明通用 VHH-抗原接触先验有效，不能直接等价为 PVRIG 实验结合或阻断能力。

```json
{
  "epitope_test_auprc": 0.13251513532736475,
  "epitope_test_auroc": 0.6691165007678898,
  "metrics_path": "/mnt/d/work/抗体/data/models/phase1_sequence_baseline/metrics.json",
  "paratope_test_auprc": 0.41744344000115485,
  "paratope_test_auroc": 0.7937550007349404,
  "vhh_score_test_pearson": 0.2908708130262476,
  "vhh_score_test_spearman": 0.1917134951120818
}
```

## 结构接触 MVP

本轮同时抽取了 SAbDab2 single-domain antibody-antigen 结构接触小样本，用于证明结构标注通路可运行。该 contact set 当前作为后续结构模型/图特征的 MVP 证据，不参与本轮序列先验训练。

```json
{
  "contact_rows": 1286,
  "cutoff_angstrom": 4.5,
  "eligible_sampled_structures": 12,
  "manifest_rows": 2422,
  "output": "/mnt/d/work/抗体/data/model_data/sabdab2_single_domain_contacts_mvp.csv",
  "processed_structures": 12,
  "stderr": "",
  "structures_with_contacts": 12
}
```

## Top 新候选预览

| candidate_id | mvp_rank_score | ai_prior_label | final_blocker_like_calibrated_label | ai_pvrig_weighted_target_probability_sum | ai_pvrig_target_hits_top50 | ai_max_paratope_probability | ai_max_pvrig_epitope_probability | recommended_next_step |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| zym_test_17428 | 0.8069838284535936 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.724345701932908 | 10 | 0.9209476113319396 | 0.8000041246414185 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_1937 | 0.8035287308549333 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.69413036108017 | 10 | 0.9207854866981506 | 0.7990238070487976 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_6823 | 0.8020455449193398 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.573958379030229 | 10 | 0.9354954361915588 | 0.7951070666313171 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_6492 | 0.8008552890597735 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.609166878461838 | 10 | 0.9291611313819884 | 0.796257495880127 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_3361596 | 0.7977167763717053 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.515374851226806 | 10 | 0.9381983876228333 | 0.7931872606277466 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_381993 | 0.7921436200504218 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.71207503080368 | 10 | 0.9040572643280028 | 0.799606204032898 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_3809 | 0.7920418374017449 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.656893754005432 | 10 | 0.9115262031555176 | 0.7978132367134094 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_21646 | 0.7881607189944034 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.300952434539797 | 10 | 0.9559046030044556 | 0.7861016392707825 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_5496 | 0.7877975812005305 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.66454873085022 | 10 | 0.9051411151885986 | 0.7980623245239258 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_6847 | 0.7877350754174937 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.492469829320909 | 10 | 0.9288312792778016 | 0.7924347519874573 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_3239184 | 0.7875005515465359 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.635440045595168 | 10 | 0.9087777137756348 | 0.7971144914627075 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_7686 | 0.7816464156392818 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.151044976711272 | 10 | 0.9685500264167786 | 0.7810924649238586 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_6720 | 0.7805185727479244 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.201950961351397 | 10 | 0.960070788860321 | 0.7827986478805542 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_1078 | 0.7804592882706202 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.428099936246872 | 10 | 0.9286198019981384 | 0.7903144955635071 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_9666 | 0.7794198204552202 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.41327956914902 | 10 | 0.9293569326400756 | 0.7898250818252563 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_2065 | 0.7788153148021894 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.479924607276915 | 10 | 0.9193735718727112 | 0.792022168636322 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_7635 | 0.7764816471578397 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.483643478155136 | 10 | 0.915946900844574 | 0.7921445369720459 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_9297 | 0.7752253568549965 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.504066491127013 | 10 | 0.9115552306175232 | 0.7928158640861511 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_3420679 | 0.7720427407216851 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.359085869789125 | 10 | 0.9276425242424012 | 0.788031816482544 | Good sequence prior but no calibrated docking consensus yet. |
| zym_test_8787 | 0.7716908584101728 | AI_PRIOR_HIGH_NEEDS_DOCKING | AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION | 14.29131301045418 | 10 | 0.9366031289100648 | 0.7857809066772461 | Good sequence prior but no calibrated docking consensus yet. |

## 如何解释分数

- `mvp_rank_score`：MVP 内部排序分数，用于在无 docking 的新候选中优先挑选下一批结构预测/docking 对象。
- `ai_prior_label`：Phase 1 序列模型对 PVRIG 目标表位的先验等级。
- `final_blocker_like_calibrated_label`：融合泄漏控制和可选 docking/consensus 后的最终计算标签。
- `CALIBRATED_BLOCKER_LIKE_A` 只能在有 docking/consensus 或数值 docking gate 支持时出现。
- `AI_PRIOR_*_NEEDS_DOCKING_CALIBRATION` 表示可以进入下一轮 docking，不是实验结合/阻断证明。

## 控制组校准

- exact known-positive 会被标记为 `EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL`，保留为阳性/泄漏控制，不参与新候选排名。
- near known-positive 或 CDR 相似控制会被标记为 `HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW`。
- mutant/control panel 用于观察流程是否把扰动阳性误当新设计。

## 一键复跑

```bash
./scripts/run_pvrig_mvp_pipeline.py --candidate-limit 500 --top-n 50
```

## 下一步

1. 对 `/mnt/d/work/抗体/data/reports/mvp_pvrig_top_candidates_v0.csv` 中的 Top 新候选批量做结构预测。
2. 对预测结构执行 8X6B / 9E6Y 双基线 docking。
3. 把 docking consensus / hotspot / occlusion 列回填后再次运行本脚本。
4. 只有通过泄漏排除且获得 calibrated blocker-like docking 证据的候选，才进入最终 Top 50。

## Scorer stdout summary

```json
{
  "candidates": 547,
  "final_label_counts": {
    "AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION": 500,
    "EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL": 18,
    "HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW": 29
  },
  "leakage_label_counts": {
    "EXACT_KNOWN_POSITIVE": 18,
    "NEAR_KNOWN_POSITIVE_OR_CDR_SIMILAR": 29,
    "NO_KNOWN_POSITIVE_LEAKAGE": 500
  },
  "output": "/mnt/d/work/抗体/data/reports/mvp_pvrig_candidate_scores_v0.csv",
  "stderr": ""
}
```
