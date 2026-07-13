# PVRIG V3-P2 Docking Gold 验证报告

- 状态：`FAIL_DOCKING_GOLD_NOT_VALIDATED`
- 协议：`DG_A_PILOT64_V1_1`
- 主批次 DG-A 完整候选：38/64
- 重复 receptor run 完整：21/32
- contact failures：0
- R_gold 重复 Spearman：None
- stable tier quadratic weighted kappa：None
- stable tier linear weighted kappa（次要）：None

## 预注册门槛

| 门槛 | 结果 |
| --- | --- |
| `package_provenance_closure` | PASS |
| `manifest_contract` | PASS |
| `main_dg_a_64_of_64` | FAIL |
| `replicate_receptor_runs_32_of_32` | FAIL |
| `contact_failures_zero` | PASS |
| `per_candidate_failure_tolerance_override_false` | PASS |
| `tolerance_relaxation_false` | PASS |
| `comparison_rows_16` | FAIL |
| `comparison_pilot_id_set_exact` | FAIL |
| `comparison_both_sides_dg_a` | FAIL |
| `repeat_R_gold_spearman_ge_0_70` | FAIL |
| `stable_tier_expected_disagreement_gt_0` | FAIL |
| `stable_tier_quadratic_kappa_ge_0_60` | FAIL |

## 解释边界

- computational docking gold from frozen independent 8X6B/9E6Y HADDOCK pipelines; not experimental binding, affinity, or blocking truth。
- `conformer_disagreement` 是两条独立 receptor docking 管线的观测差异，同时包含构象与采样差异，不是纯构象因果效应。
- 16 条重复序列的指标衡量端到端 docking 重复性，不代替实验绑定或阻断验证。
