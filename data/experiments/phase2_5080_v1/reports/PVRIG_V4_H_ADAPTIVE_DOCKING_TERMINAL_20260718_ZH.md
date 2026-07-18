# PVRIG V4-H 自适应双构象 Docking 终态汇总

## 终态

- 候选总数：1320
- 可分析候选：1281
- Stage 1：2636/2640成功，4条技术失败
- Stage 2：768/768成功
- Stage 3：255/256成功，1条技术失败
- Stage 2入选：384个候选
- Stage 3入选：128个候选
- 最终证据层级：{'DUAL_1_SEED': 917, 'DUAL_2_SEED': 241, 'DUAL_3_SEED': 123, 'TECHNICAL_INCOMPLETE': 39}
- 总技术失败：5条

## 关键文件

- `final_adaptive_seed_ranking.tsv`：1320条最终排名。
- `final_top50.tsv`、`final_top128.tsv`：便于人工检查的短名单。
- `stage1_seed917_ranking.tsv`：第一随机种子排名。
- `stage2_seed917_1931_ranking.tsv`：两随机种子排名。
- `stage2_selected_seed1931_candidates.tsv`、`stage3_selected_seed3253_candidates.tsv`：分阶段入选候选。
- `technical_failures.tsv`：5条技术失败。
- `ADAPTIVE_DOCKING_RECEIPT.json`：远端正式终态收据。
- `final_local_package_receipt.json`、`SHA256SUMS`：本地物化和校验收据。

## 重型原始文件

逐任务运行目录、`job_result.json`和所有pose PDB仍保存在：

`/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717`

本地包未复制重型pose目录，避免无必要的数据膨胀。

## 证据边界

以上结果表示计算阻断样几何和多随机种子稳定性，不等于真实结合、Kd或实验阻断。
