# PVRIG 阳性优先完整筛选校准 V1

日期：2026-07-24  
状态：`PASS_POSITIVE_BASELINE_AND_CONTROL_EXPANSION_READY`

## 结论

第一轮阳性优先校准已经完成，并已扩展到 36 条扰动控制和 47 条 V3 双构象多 seed 控制。

- 11/11 阳性序列为标准 20 AA；
- 11/11 ANARCI/IMGT L1 编号完整；
- 11/11 NanoBodyBuilder2 单体结构存在；
- 11/11 在 V3 的 `8X6B + 9E6Y`、每构象 3 seed 中均达到“每构象至少 2 seed 为 A/B 支持”；
- 只有 5/11 达到双构象 robust strict-A，所以 strict-A 不能作为 blocker 硬门；
- 官方 validator 对 11 条为 0/11 通过，这是正确的阳性泄漏排除，不是生物学失败。

## 比赛边界

官方要求：

1. 最多提交 50 条，通常每队不超过 10 条进入实验；
2. VHH 按 ANARCI/IMGT 定义 CDR；
3. 每个对应 CDR 与任一已知阳性原则上低于 80% identity；
4. 初筛权重为 BLI 单浓度 70%、表达 20%、纯度 10%；
5. 复筛权重为 Kd 排名 50%、竞争 ELISA IC50 排名 50%；
6. 目标是 PVRIG 胞外区、PVRL2 界面和阻断机制。

因此本流程保留两个独立结论：

- `CALIBRATION_POSITIVE_RECALLED`：阳性被技术、结构和机制校准层召回；
- `CALIBRATION_POSITIVE_EXCLUDED_LEAKAGE`：同一阳性在比赛提交层被正确排除。

## 本次校准推翻的过严门控

| 单项旧门槛 | 阳性反例 | 新处理 |
|---|---:|---|
| L2/VHH-like 必须 PASS | 7/11 非 PASS | warn/rank |
| TNP 必须全绿 | 2/11 PNC red | 单项 red 只预警 |
| Sapiens 必须 >=0.70 | 3/11 低于 0.70 | 人源化负担排序 |
| Cys 必须等于 2 | 10/11 不等于 2 | 2 或有结构支持的 4 可接受 |
| 不能出现 hydrophobic 5-mer | 1/11 出现 1 个 | 1 个预警，多个再升级 |
| strict-A 必须通过 | 仅 5/11 robust strict-A | rank-only |

这些指标仍用于表达、纯化、稳定性和成药性排序，但不能单独否决 blocker。

## V3 47 控制面板

- 47 个实体；
- 282/282 控制作业成功；
- 18/18 positive-control 实体 robust A/B；
- 14 个 destructive alanine 控制中，4/14 仍 robust strict-A；
- 说明 A/B 是高召回的界面合理性门，而不是 blocker 特异性证明。

破坏性突变尚无实验 non-binder/non-blocker 真值，所以本报告只称“计算扰动控制”。

## 静态亲和力与软件结论

- PRODIGY：弱 prior；
- FoldX 跨候选绝对排序：不启用；
- FoldX fixed-parent ΔΔG：诊断；
- Graphinity 当前多突变排名：拒绝；
- Rosetta InterfaceAnalyzer：等待同面板校准；
- MD/MMGBSA：等待配对阳性/扰动校准，且仅用于末端 20–50 条。

任何软件只有同时达到：

- 阳性召回 >=0.80；
- 控制假阳性 <=0.30；
- entity AUROC >=0.70；
- leave-one-family-out 方向一致 >=0.70；

才允许从描述性字段升级为排名证据；即使升级也不是实验 Kd/IC50。

## 逐步扩大状态

| stage | input_entities | completed_entities | primary_result | status | next_action |
| --- | --- | --- | --- | --- | --- |
| S0_positive11_sequence_qc | 11 | 11 | 11/11 standard AA and L1 numbering PASS | PASS | retain as biological calibration; exclude from submission novelty lane |
| S1_positive11_structure_old_docking | 11 | 11 | 109 old consensus poses; 11/11 NBB2 and consensus present | PASS | use only as historical geometry calibration |
| S2_control36_perturbation | 36 | 36 | 357 consensus poses; leakage exact=7, near=29 | PASS_WITH_SPECIFICITY_WARNING | do not call perturbations experimental negatives |
| S3_v3_control47_dual_conformation_3seed | 47 | 47 | 282/282 jobs SUCCESS; positive robust A/B 18/18; patent11 robust A/B 11/11; patent11 robust strict-A 5/11; destructive robust strict-A 4/14 | PASS_HIGH_SENSITIVITY_SPECIFICITY_LIMITED | keep strict-A and HADDOCK score as rank features, not hard truth |
| S4_core448_existing_evidence_audit | 448 | 448 | fresh ANARCI H 448/448; CDR exact match 437/448; boundary review 11 | PASS_WITH_CDR_BOUNDARY_REVIEW | quarantine 11 CDR2-boundary rows; run official validator/full positive library on all 448 |
| S5_strict6042_cascade | 6042 | 6042 | 4976 conservative developability pass; 448 CORE_A | READY_NOT_FINAL | apply calibrated policy in chunks; never overwrite frozen dry-run |

## 下一批执行边界

1. 先对 448 CORE_A 跑完整官方 validator 和完整阳性库 CDR 审计；
2. 用本次校准后的 developability 规则复核，不再用 Cys=2/TNP 全绿作 blocker 硬门；
3. 从 448 中按 parent、CDR3、route 和模型分歧抽取约 200 条静态能量面板；
4. Rosetta 只有通过阳性/控制面板才参与候选排序；
5. MD 仅进入 20–50 条末端复核；
6. 最终 50 条和优先 10 条必须重新跑官方 validator、哈希和多样性冻结。

## 机器可读文件

- `positive11_evidence.tsv`
- `control36_evidence.tsv`
- `v3_control47_evidence.tsv`
- `CALIBRATED_SCREENING_POLICY_V1.json`
- `EXPANSION_STAGE_STATUS.tsv`
- `STATUS.json`
- `fresh_numbering/positive11_anarci_H.csv`
- `expansion/core448/NUMBERING_RECEIPT.json`
- `expansion/core448/core437_numbering_pass.tsv`
- `expansion/core448/core11_numbering_review.tsv`
- `SHA256SUMS`
