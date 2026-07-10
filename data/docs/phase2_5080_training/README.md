# Phase 2: RTX 5080 结构+序列 PVRIG-VHH 模型升级总规划

Updated: 2026-07-09

## 目标

在当前 MVP 的基础上，升级为一个可以在本地 RTX 5080 上训练的结构+序列多任务模型，用于：

1. 预测 VHH 的 paratope residue；
2. 预测抗原/PVRIG 的 epitope residue；
3. 预测 VHH-antigen residue-pair contact map；
4. 对 VHH-PVRIG 候选给出 binding-prior score；
5. 对 PVRIG-PVRL2 interface / hotspot 覆盖给出 blocker-prior score；
6. 输出可解释的 Top 候选、候选 CDR 贡献、PVRIG 目标区域覆盖和评估指标。

## 当前状态

已有 MVP 输出：

| 资产 | 路径 | 用途 |
| --- | --- | --- |
| MVP 主报告 | `reports/MVP_PVRIG_VHH_WORKFLOW_REPORT.md` | 当前 baseline 流程说明 |
| MVP 验收 | `reports/MVP_COMPLETION_AUDIT.md` | 当前流程 PASS 证据 |
| 候选池 | `model_data/mvp_candidates_v0.csv` | 500 新候选 + 控制组 |
| Top 新候选 | `reports/mvp_pvrig_top_candidates_v0.csv` | 下一轮结构预测/docking 起点 |
| Phase 1 小模型 | `models/phase1_sequence_baseline/` | NumPy 线性 baseline |
| PVRIG mask | `model_data/pvrig_full_sequence_mask_v0.csv` | PVRIG hotspot/interface 监督 |
| SAbDab2 contact MVP | `model_data/sabdab2_single_domain_contacts_mvp.csv` | 结构接触抽取通路验证 |

当前机器检查：

```text
GPU: NVIDIA GeForce RTX 5080, 16GB VRAM
CUDA driver: nvidia-smi shows CUDA Version 13.2
Current Python env: torch/sklearn/Bio/gemmi missing; numpy/pandas available
```

因此 Phase 2 必须单独建训练环境，不污染当前可复跑 MVP 环境。

## 文件夹区分

文档放在：

```text
docs/phase2_5080_training/
```

训练实验放在：

```text
experiments/phase2_5080_v1/
  configs/        # yaml/json 配置
  data_splits/    # train/val/test split manifest
  prepared/       # 训练前处理后的 npz/parquet/jsonl
  negative_sets/  # 负样本池和抽样审计
  checkpoints/    # 模型权重
  runs/           # 单次训练运行目录
  reports/        # 指标报告
  logs/           # stdout/stderr/tensorboard/csv logs
  predictions/    # val/test/PVRIG candidate prediction
  audits/         # 完成审计、泄漏审计、数据审计
  src/            # Phase 2 专用训练代码
```

当前 MVP 资产继续保留在：

```text
model_data/
models/phase1_sequence_baseline/
reports/
scripts/
```

Phase 2 不直接覆盖 Phase 1/MVP 文件。

## Phase 2 交付物

最低完成标准：

| 编号 | 交付物 | 路径 |
| --- | --- | --- |
| D1 | 数据划分 manifest | `experiments/phase2_5080_v1/data_splits/*.csv` |
| D2 | 负样本设计和实际负样本表 | `experiments/phase2_5080_v1/negative_sets/*.csv` |
| D3 | 训练配置 | `experiments/phase2_5080_v1/configs/phase2_v1.yaml` |
| D4 | 训练代码 | `experiments/phase2_5080_v1/src/` |
| D5 | 训练日志和 checkpoint | `experiments/phase2_5080_v1/runs/` + `checkpoints/` |
| D6 | train/val/test 指标 | `experiments/phase2_5080_v1/reports/phase2_v1_eval.md` |
| D7 | PVRIG Top 候选重评分 | `experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2.csv` |
| D8 | 完成审计 | `experiments/phase2_5080_v1/audits/PHASE2_COMPLETION_AUDIT.md` |

## 推荐执行顺序

1. 准备独立 GPU 训练环境；
2. 全量抽取 SAbDab2 single-domain contact map；
3. 构建 pair-level positive / negative 数据；
4. 建立严格 train/val/test split；
5. 训练 sequence+contact 多任务模型；
6. 在验证集调阈值，不碰测试集；
7. 在测试集报告固定指标；
8. 对 PVRIG Top 50 做 Phase 2 重评分；
9. 将 Phase 2 score 和 docking gate 合并，输出下一批结构预测/docking 优先级。

## 参考文档

- `docs/phase2_5080_training/FOLDER_CONTRACT.md`
- `docs/phase2_5080_training/DATA_SPLIT_PLAN.md`
- `docs/phase2_5080_training/NEGATIVE_SAMPLING_DESIGN.md`
- `docs/phase2_5080_training/MODEL_ARCHITECTURE_V1.md`
- `docs/phase2_5080_training/TRAINING_AND_EVALUATION_PROTOCOL.md`

## 2026-07-09 已执行的 Phase 2 V1 训练

本阶段已经不只是规划：已在本地 RTX 5080 环境完成一次 `VHH-Ag CrossContactNetV1` 训练和评估。

关键产物：

| 类型 | 路径 |
| --- | --- |
| 环境审计 | `experiments/phase2_5080_v1/audits/environment_audit.md` |
| split/negative manifest 审计 | `experiments/phase2_5080_v1/audits/phase2_manifest_build_audit.md` |
| 训练脚本 | `experiments/phase2_5080_v1/src/train_phase2_v1.py` |
| 训练日志 | `experiments/phase2_5080_v1/logs/phase2_v1_20260709_5080_seed7.log` |
| best checkpoint | `experiments/phase2_5080_v1/checkpoints/phase2_v1_best_checkpoint.pt` |
| test metrics | `experiments/phase2_5080_v1/runs/phase2_v1_20260709_5080_seed7/test_metrics.json` |
| 评估报告 | `experiments/phase2_5080_v1/reports/phase2_v1_eval.md` |
| PVRIG Top 重评分 | `experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v1.csv` |
| 训练完成审计 | `experiments/phase2_5080_v1/audits/PHASE2_TRAINING_COMPLETION_AUDIT.md` |

核心结果：

```text
Phase2 paratope test AUPRC: 0.6244  vs Phase1 0.4174
Phase2 epitope  test AUPRC: 0.1541  vs Phase1 0.1325
Phase2 weak-contact proxy test AUPRC: 0.6863
Phase2 pair binding test AUROC/AUPRC: 0.5153 / 0.2684
```

结论：site-level 架构升级有效；pair binding head 仍弱，下一步应升级 cross-attention/top-k contact pooling 并接入真实结构 contact-map 训练。

## 2026-07-09 已执行的 Phase 2 V2 真实 contact-map 训练

V2 已完成真实训练，不再只是 weak-contact proxy：

| 类型 | 路径 |
| --- | --- |
| V2 contact-map 构建脚本 | `experiments/phase2_5080_v1/src/build_structure_contact_maps_v2.py` |
| V2 真实 contact-map JSONL | `experiments/phase2_5080_v1/prepared/structure_contact_maps_v2.jsonl` |
| V2 contact-map summary | `experiments/phase2_5080_v1/prepared/structure_contact_maps_v2_summary.csv` |
| V2 contact-map 审计 | `experiments/phase2_5080_v1/audits/structure_contact_maps_v2_audit.md` |
| V2 训练脚本 | `experiments/phase2_5080_v1/src/train_phase2_v2.py` |
| V2 训练日志 | `experiments/phase2_5080_v1/logs/phase2_v2_20260709_5080_seed17.log` |
| V2 best checkpoint | `experiments/phase2_5080_v1/checkpoints/phase2_v2_best_checkpoint.pt` |
| V2 test metrics | `experiments/phase2_5080_v1/runs/phase2_v2_20260709_5080_seed17/test_metrics.json` |
| V2 评估报告 | `experiments/phase2_5080_v1/reports/phase2_v2_eval.md` |
| V2 PVRIG 重评分 | `experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2.csv` |
| V2 完成审计 | `experiments/phase2_5080_v1/audits/PHASE2_V2_COMPLETION_AUDIT.md` |

V2 数据：

```text
Real contact-map records: 371
Real positive contact pairs <=4.5 A: 32807
Real non-contact negative pairs >=8.0 A: 131228
Contact split: train 290 / val 49 / test 32 records
```

V2 指标：

```text
Contact test AUROC/AUPRC: 0.8728 / 0.6559
Contact positive rate: 0.2056
Pair test AUROC/AUPRC: 0.5180 / 0.2708
Paratope test AUROC/AUPRC: 0.8804 / 0.5795
Epitope test AUROC/AUPRC: 0.5888 / 0.1066
PVRIG prediction rows: 50, all NO_KNOWN_POSITIVE_LEAKAGE
```

解释：V2 真实 contact-map 头有效，AUPRC 明显高于 contact positive rate；pair binding 仍弱，只比 V1 轻微提升，不能作为最终 binder/blocker 判定。下一步应把 pair binding 换成 contrastive/ranking objective，并引入 docking pose/non-blocker negatives。

## 2026-07-09 已完成的 Phase 2 V2.1 Expanded800 训练

V2.1 的目的不是替换 V2 的结论，而是把真实 heavy-atom contact-map 训练集从 V2 的 160 个结构样本扩到 800 个结构样本，并重新训练/评估一版可交付模型。

交付状态：`PASS`

关键产物：

| 类型 | 路径 |
| --- | --- |
| V2.1 contact-map JSONL | `experiments/phase2_5080_v1/prepared/structure_contact_maps_v2_expanded800.jsonl` |
| V2.1 contact-map summary | `experiments/phase2_5080_v1/prepared/structure_contact_maps_v2_expanded800_summary.csv` |
| V2.1 contact-map 审计 | `experiments/phase2_5080_v1/audits/structure_contact_maps_v2_expanded800_audit.md` |
| V2.1 训练日志 | `experiments/phase2_5080_v1/logs/phase2_v2_1_expanded800_20260709_seed31.log` |
| V2.1 best checkpoint | `experiments/phase2_5080_v1/checkpoints/phase2_v2_1_expanded800_best_checkpoint.pt` |
| V2.1 test metrics | `experiments/phase2_5080_v1/runs/phase2_v2_1_expanded800_20260709_seed31/test_metrics.json` |
| V2.1 评估报告 | `experiments/phase2_5080_v1/reports/phase2_v2_1_expanded800_eval.md` |
| V2.1 对比 JSON | `experiments/phase2_5080_v1/reports/phase2_v2_1_expanded800_comparison.json` |
| V2.1 PVRIG 重评分 | `experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2_1_expanded800.csv` |
| V2.1 完成审计 | `experiments/phase2_5080_v1/audits/PHASE2_V2_1_EXPANDED800_AUDIT.md` |
| V2.1 最终验证脚本 | `experiments/phase2_5080_v1/src/validate_phase2_v2_1_training.py` |
| V2.1 最终验证报告 | `experiments/phase2_5080_v1/audits/PHASE2_V2_1_FINAL_VALIDATION.md` |

V2.1 数据：

```text
Input structures sampled: 800
Real contact-map records: 2725
Real positive contact pairs <=4.5 A: 293937
Real non-contact negative pairs >=8.0 A: 1175748
Contact split: train 1932 / val 475 / test 318 records
```

V2.1 指标：

```text
Contact test AUROC/AUPRC: 0.8617 / 0.6157
Contact positive rate: 0.2000
Pair test AUROC/AUPRC: 0.5160 / 0.2686
Paratope test AUROC/AUPRC: 0.9097 / 0.6411
Epitope test AUROC/AUPRC: 0.6854 / 0.1839
PVRIG prediction rows: 50, all NO_KNOWN_POSITIVE_LEAKAGE
```

相对 V1/V2 的结论：

- 数据规模：contact records 从 V2 的 371 扩到 2725，约 7.35x。
- contact head：V2.1 的 AUPRC `0.6157` 低于小样本 V2 的 `0.6559`，但测试集从 32 records 扩到 318 records，仍显著高于随机正例率 `0.2000`。
- site heads：paratope AUPRC 从 V1 `0.6244` 提升到 V2.1 `0.6411`；epitope AUPRC 从 V1 `0.1541` 提升到 V2.1 `0.1839`。
- pair head：仍弱，AUROC `0.5160` / AUPRC `0.2686`，不能当作最终 binder/blocker 证明。

边界：V2.1 是完成的计算训练/评估包，可用于候选优先级排序和下一轮结构计算优先级；它不证明实验结合、Kd、IC50 或真实 PVRIG-PVRL2 阻断效果。

## 2026-07-09 已完成的 Phase 2 V2.2 Full2277 训练

V2.2 在 V2.1 的基础上继续扩大真实 contact-map 数据集：使用 full2277 结构 contact 数据训练，不覆盖 V2.1 产物。V2.2 是当前 Phase 2 的最新完成版。

交付状态：`PASS`

关键产物：

| 类型 | 路径 |
| --- | --- |
| V2.2 contact-map JSONL | `experiments/phase2_5080_v1/prepared/structure_contact_maps_v2_full2277.jsonl` |
| V2.2 contact-map summary | `experiments/phase2_5080_v1/prepared/structure_contact_maps_v2_full2277_summary.csv` |
| V2.2 contact-map 审计 | `experiments/phase2_5080_v1/audits/structure_contact_maps_v2_full2277_audit.md` |
| V2.2 训练日志 | `experiments/phase2_5080_v1/logs/phase2_v2_2_full2277_20260709_seed41.log` |
| V2.2 best checkpoint | `experiments/phase2_5080_v1/checkpoints/phase2_v2_2_full2277_best_checkpoint.pt` |
| V2.2 test metrics | `experiments/phase2_5080_v1/runs/phase2_v2_2_full2277_20260709_seed41/test_metrics.json` |
| V2.2 评估报告 | `experiments/phase2_5080_v1/reports/phase2_v2_2_full2277_eval.md` |
| V2.2 对比 JSON | `experiments/phase2_5080_v1/reports/phase2_v2_2_full2277_comparison.json` |
| V2.2 PVRIG 重评分 | `experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv` |
| V2.2 完成审计 | `experiments/phase2_5080_v1/audits/PHASE2_V2_2_FULL2277_AUDIT.md` |
| V2.2 最终验证脚本 | `experiments/phase2_5080_v1/src/validate_phase2_v2_2_training.py` |
| V2.2 最终验证报告 | `experiments/phase2_5080_v1/audits/PHASE2_V2_2_FULL2277_FINAL_VALIDATION.md` |

V2.2 数据：

```text
Input structures sampled: 2259
Real contact-map records: 8414
Real positive contact pairs <=4.5 A: 855922
Real non-contact negative pairs >=8.0 A: 3423688
Contact split: train 6068 / val 1462 / test 884 records
```

V2.2 指标：

```text
Contact test AUROC/AUPRC: 0.8975 / 0.7242
Contact positive rate: 0.2082
Pair test AUROC/AUPRC: 0.5833 / 0.3338
Paratope test AUROC/AUPRC: 0.9143 / 0.6477
Epitope test AUROC/AUPRC: 0.7209 / 0.2272
PVRIG prediction rows: 50, all NO_KNOWN_POSITIVE_LEAKAGE
```

相对 V2.1 的变化：

- 数据规模：contact records 从 `2725` 增至 `8414`，约 `3.09x`；positive contact pairs 从 `293937` 增至 `855922`。
- contact head：AUPRC 从 `0.6157` 提升到 `0.7242`，测试集 records 从 `318` 增至 `884`。
- site heads：paratope AUPRC 从 `0.6411` 提升到 `0.6477`；epitope AUPRC 从 `0.1839` 提升到 `0.2272`。
- pair head：AUROC/AUPRC 从 `0.5160 / 0.2686` 提升到 `0.5833 / 0.3338`，但仍未达到可单独作为 binder/blocker 判定的强度。

边界：V2.2 是当前最强的计算优先级模型，可用于候选排序和下一轮结构计算优先级；它仍不证明实验结合、Kd、IC50 或真实 PVRIG-PVRL2 阻断效果。下一步应把 pair-level objective 改成 ranking/contrastive，并加入 docking pose / non-blocker hard negatives。
