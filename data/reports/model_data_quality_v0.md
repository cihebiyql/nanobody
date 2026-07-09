# Phase 0 模型数据索引质量报告

生成目标：为 PVRIG 方向 VHH-抗原结合小模型建立统一训练索引。

## 产物

- `model_data/index_v0_samples.csv`：统一样本索引，共 37711 行。
- `model_data/index_v0_samples.jsonl.gz`：同一索引的 JSONL 压缩版本。
- `model_data/source_summary_v0.csv`：各数据源统计。
- `model_data/pvrig_target_epitope_v0.csv`：PVRIG 目标阻断表位/热点。
- `model_data/pvrig_full_sequence_mask_v0.csv`：PVRIG 全长逐残基 target mask。
- `model_data/sabdab2_single_domain_structure_manifest_v0.csv`：SAbDab2 single-domain 结构 manifest；接触抽取待下一阶段。

## 数据源统计

| source_dataset | split | status | rows | mask_len_ok_vhh | mask_len_ok_antigen | with_binding_label | unique_pdb | cdr_spans_found | unique_vhh_seq | known_kd_nm | unique_antigen_name | with_epitope_residues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ZYMScott_Paratope | train | ok | 851 | 851.0 | 851.0 | 21.0 | 510.0 |  |  |  |  |  |
| ZYMScott_Paratope | val | ok | 139 | 139.0 | 139.0 | 2.0 | 122.0 |  |  |  |  |  |
| ZYMScott_Paratope | test | ok | 240 | 240.0 | 240.0 | 3.0 | 149.0 |  |  |  |  |  |
| ZYMScott_vhh_affinity-score | train | ok | 8915 |  |  | 8915.0 |  | 8915.0 | 8914.0 |  |  |  |
| ZYMScott_vhh_affinity-score | val | ok | 1274 |  |  | 1274.0 |  | 1274.0 | 1274.0 |  |  |  |
| ZYMScott_vhh_affinity-score | test | ok | 2548 |  |  | 2548.0 |  | 2548.0 | 2548.0 |  |  |  |
| ZYMScott_vhh_affinity-seq | train | ok | 8888 |  |  | 8888.0 |  | 8888.0 | 8888.0 |  |  |  |
| ZYMScott_vhh_affinity-seq | val | ok | 1302 |  |  | 1302.0 |  | 1302.0 | 1302.0 |  |  |  |
| ZYMScott_vhh_affinity-seq | test | ok | 2547 |  |  | 2547.0 |  | 2547.0 | 2546.0 |  |  |  |
| sdAb-DB | all | ok | 1484 |  |  |  |  |  | 1030.0 | 272.0 | 110.0 |  |
| silicobio_sabdab_training | all | ok | 9523 |  |  |  | 4920.0 |  |  |  |  | 9486.0 |

## PVRIG / 结构统计

- `pvrig_sequence_length`: 326
- `pvrig_hotspot_rows`: 26
- `pvrig_target_positions`: 24
- `sabdab2_single_domain_manifest_rows`: 2422
- `sabdab2_single_domain_with_antigen_chain`: 2277
- `sabdab2_single_domain_status`: manifest_built_contacts_pending

## 重要限制

- 当前环境没有 `pyarrow`，因此本阶段没有输出 parquet；使用 `csv` 和 `jsonl.gz` 作为稳定交换格式。
- 当前环境没有 `BioPython/gemmi`，因此 SAbDab2 single-domain 结构只生成 manifest，未在本脚本中抽取 4.5 Å 接触。
- `ZYMScott_vhh_affinity-score/seq` 没有 antigen 序列字段，适合作为 VHH 分数/排序监督，不应当单独解释为任意 VHH-antigen pair 的亲和力。
- `sdAb-DB` 的 antigen 多数是名称而不是序列，已保留 Kd 和名称，后续需要解析 UniProt/PDB 才能用于 pair 模型。
- `silicobio_sabdab_training` 多为常规 VH/VL 抗体，可用于抗原 epitope 头，但不要当成 VHH-only 主监督。

## 下一步建议

1. 安装或引入结构解析依赖后，从 `sabdab2_single_domain_structure_manifest_v0.csv` 抽取 VHH-antigen 4.5 Å paratope/epitope 接触。
2. 用 `index_v0_samples.csv` 先训练一个 sequence-only baseline：paratope head + epitope head + ranking head。
3. 对 PVRIG 推理时，把 `pvrig_full_sequence_mask_v0.csv` 作为目标 epitope overlap 约束。
