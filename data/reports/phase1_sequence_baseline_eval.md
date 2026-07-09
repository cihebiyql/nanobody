# Phase 1 Sequence-only Baseline 训练报告

本阶段目标：不依赖 PyTorch/sklearn，先用纯 NumPy 跑通一个可训练、可保存、可评估的小模型闭环。

## 模型组成

- `paratope_logistic_head.npz`：VHH 每个残基是否为 paratope 的 logistic head。
- `epitope_logistic_head.npz`：抗原每个残基是否为 epitope 的 logistic head。
- `vhh_score_ridge_head.npz`：基于 VHH/CDR 组成特征的 VHH-only score ridge head。

## Paratope Metrics

| split | auprc | auroc | f1_at_0p5 | fn | fp | n | positive_rate | precision_at_0p5 | recall_at_0p5 | tn | tp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 0.4493 | 0.7997 | 0.4785 | 4647.0000 | 23942.0000 | 102664.0000 | 0.1730 | 0.3539 | 0.7384 | 60960.0000 | 13115.0000 |
| val | 0.4590 | 0.8013 | 0.4767 | 768.0000 | 3887.0000 | 16880.0000 | 0.1711 | 0.3529 | 0.7341 | 10105.0000 | 2120.0000 |
| test | 0.4174 | 0.7938 | 0.4585 | 1255.0000 | 7155.0000 | 29287.0000 | 0.1644 | 0.3322 | 0.7394 | 17317.0000 | 3560.0000 |

## Epitope Metrics

| split | auprc | auroc | f1_at_0p5 | fn | fp | n | positive_rate | precision_at_0p5 | recall_at_0p5 | tn | tp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 0.1376 | 0.6891 | 0.1983 | 5607.0000 | 101725.0000 | 258880.0000 | 0.0729 | 0.1154 | 0.7031 | 138273.0000 | 13275.0000 |
| val | 0.1434 | 0.7091 | 0.1996 | 940.0000 | 16580.0000 | 45085.0000 | 0.0693 | 0.1164 | 0.6992 | 25380.0000 | 2185.0000 |
| test | 0.1325 | 0.6691 | 0.1886 | 1821.0000 | 29041.0000 | 74725.0000 | 0.0724 | 0.1099 | 0.6633 | 40276.0000 | 3587.0000 |

## VHH-only Score Metrics

| split | mae | n | pearson | rmse | spearman |
| --- | --- | --- | --- | --- | --- |
| train | 0.5349 | 8888.0000 | 0.2288 | 0.9059 | 0.1335 |
| val | 0.5723 | 1302.0000 | 0.1847 | 0.9452 | 0.0881 |
| test | 3.0541 | 2547.0000 | 0.2909 | 3.6882 | 0.1917 |

## 重要解释

- 这只是 baseline，不是最终模型；它证明当前数据可以进入训练闭环。
- paratope/epitope 头是 residue-level 二分类，主训练数据是 ZYMScott Paratope。
- VHH score 头不是任意 VHH-antigen pair 亲和力模型，因为源数据没有 antigen 序列字段。
- 后续应补 SAbDab2 single-domain 结构接触抽取，并替换/增强为 ESM/AntiBERTy embedding + cross-attention。

## 推理脚本与 PVRIG smoke test

新增脚本：`scripts/score_phase1_sequence_baseline.py`。

示例用途：输入候选 VHH 序列和 PVRIG FASTA，输出：

- VHH top paratope residues
- antigen/PVRIG top epitope residues
- VHH-only raw score
- PVRIG target epitope overlap，包括 threshold overlap、Top-20 overlap、Top-50 overlap

本次 smoke test 输出：

- 文件：`reports/phase1_pvrig_smoke_prediction.json`
- 输入：`ZYMScott_vhh_affinity-seq/test.csv` 第一条 VHH + `model_data/pvrig_target_sequence_v0.fasta`
- 目的：只验证推理链路可运行，不代表该 VHH 真实结合 PVRIG。
- 结果摘要：threshold=0.5 时 predicted epitope count 偏多，说明 baseline 概率未校准；因此后续更应使用 Top-K overlap 与 docking/结构接触复核。

## 最后校准层补充

Phase 1 baseline 只负责给出 AI prior：paratope、epitope、VHH-only score 和 PVRIG target overlap。已知 WO2021180205A1 阳性 VHH/HCVR 与 mutant/control panel 不进入普通训练集，而是作为最终校准层：

- `model_data/pvrig_blocker_positive_calibration_v0.csv`：11 条 known positive/blocking VHH/HCVR。
- `model_data/pvrig_blocker_positive_pose_labels_v0.csv`：109 条 positive pose consensus labels。
- `model_data/pvrig_blocker_mutant_control_calibration_v0.csv`：36 条 mutant/control，含 exact/near known-positive leakage 标签。
- `model_data/pvrig_blocker_mutant_pose_labels_v0.csv`：357 条 mutant/control pose labels。
- `model_data/pvrig_blocker_threshold_sensitivity_v0.csv`：162 条阈值敏感性记录。

最终候选必须经过 `reports/pvrig_blocker_final_calibration_layer_v0.md` 描述的 leakage / dual-baseline consensus / threshold sensitivity / mutant false-positive gate，才能给出 calibrated blocker-like 标签。

## 批量候选校准脚本

新增：`scripts/score_pvrig_candidates_with_calibration.py`。

它把 Phase 1 sequence-only 模型输出与 `model_data/pvrig_blocker_*` 最终校准层合并，支持候选 CSV/FASTA 批量输出：AI prior、PVRIG target overlap、known-positive leakage、可选 docking consensus、最终 calibrated label。说明见 `reports/pvrig_candidate_calibrated_scoring_v0.md`。

