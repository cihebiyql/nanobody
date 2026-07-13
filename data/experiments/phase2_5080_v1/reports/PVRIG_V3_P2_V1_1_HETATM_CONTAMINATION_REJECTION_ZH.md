# PVRIG V3-P2 V1.1 HETATM 污染拒绝诊断

- 审计状态：`REJECT_V1_1_HETATM_CONTAMINATION_CONFIRMED`
- 范围：当前 8-run revised smoke；未读取、未验证完整 Pilot64 Gold 输出。
- 行数：156 个 `run × baseline × model` 记录。
- 只读性：输入树审计前后 SHA256 快照一致 = `true`。

## 结论

当前 V1.1 遮挡计分把参考 PVRL2 链中的水和配体 `HETATM` 当作 PVRL2 残基，
并计入 total/CDR3 residue-pair occlusion。该语义已经在全量 Pilot64 运行前被本审计拒绝，
因此当前 V1.1 路径不得冻结为训练用 Docking Gold。

这里的 protein-only 结果仅是 **sensitivity classification comparison（敏感性分类比较）**。
它不是 V1.2 校准标签、不是 corrected Docking Gold，也不是实验结合或阻断真值。

## 独立复现门

- 当前 inclusive total/CDR3/fraction 精确复现：156/156。
- 当前分类逻辑独立复现：156/156。
- CSV/JSON/mechanism/rank 来源一致：156/156。
- 复算仅改变参考 PVRL2 的 record filter：`ATOM + HETATM` → `ATOM`；altloc、坐标、CDR 范围、4.5 Å cutoff 和 hotspot 均不变。

## 参考结构污染清单

| baseline | PVRL2 chain | protein ATOM / residues | HETATM / residues | HOH / residues | EDO / residues | other |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 8X6B | A | 963 / 126 | 58 / 58 | 58 / 58 | 0 / 0 | 0 / 0 |
| 9E6Y | D | 1002 / 130 | 84 / 66 | 60 / 60 | 24 / 6 | 0 / 0 |

## 污染影响

- total count 受影响：156/156。
- CDR3 count 受影响：156/156。
- CDR3 fraction 改变：156/156。
- 当前规则下分类变化：18/156（11.54%）。

| 指标 | min | median | mean | p90 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| current/protein-only total factor | 1.1354 | 1.2467 | 1.2478 | 1.2908 | 1.3270 |
| current/protein-only CDR3 factor | 1.0805 | 1.1994 | 1.2026 | 1.2848 | 1.4444 |
| current fraction - protein-only fraction | -0.04006 | -0.01113 | -0.01010 | 0.00482 | 0.04342 |

fraction delta 有正有负，不能统一描述为 fraction 膨胀。

## 当前规则下的敏感性分类比较

| class | current V1.1 | protein-only sensitivity |
| --- | ---: | ---: |
| `BLOCKER_LIKE_A` | 64 | 60 |
| `BLOCKER_PLAUSIBLE_B` | 85 | 75 |
| `EVIDENCE_INFERENCE_ONLY_E` | 7 | 21 |

分类 transition：

- `BLOCKER_LIKE_A->BLOCKER_PLAUSIBLE_B`：4
- `BLOCKER_PLAUSIBLE_B->EVIDENCE_INFERENCE_ONLY_E`：14

变化行：

- `P2PILOT_001__8X6B__main|8x6b|cluster_3_model_3`
- `P2PILOT_001__8X6B__main|8x6b|cluster_4_model_3`
- `P2PILOT_001__8X6B__main|9e6y|cluster_3_model_3`
- `P2PILOT_001__8X6B__main|9e6y|cluster_4_model_3`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_5_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_1_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_5_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_7_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_7_model_2`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_2_model_2`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_7_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_7_model_2`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_2_model_2`
- `P2PILOT_033__8X6B__main|8x6b|cluster_6_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_6_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_3_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_3_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_1_model_1`

## 全部受影响行标识

- `P2PILOT_001__8X6B__main|8x6b|cluster_1_model_1`
- `P2PILOT_001__8X6B__main|8x6b|cluster_2_model_1`
- `P2PILOT_001__8X6B__main|8x6b|cluster_3_model_1`
- `P2PILOT_001__8X6B__main|8x6b|cluster_3_model_2`
- `P2PILOT_001__8X6B__main|8x6b|cluster_4_model_1`
- `P2PILOT_001__8X6B__main|8x6b|cluster_3_model_3`
- `P2PILOT_001__8X6B__main|8x6b|cluster_4_model_2`
- `P2PILOT_001__8X6B__main|8x6b|cluster_5_model_1`
- `P2PILOT_001__8X6B__main|8x6b|cluster_4_model_3`
- `P2PILOT_001__8X6B__main|8x6b|cluster_2_model_2`
- `P2PILOT_001__8X6B__main|9e6y|cluster_1_model_1`
- `P2PILOT_001__8X6B__main|9e6y|cluster_2_model_1`
- `P2PILOT_001__8X6B__main|9e6y|cluster_3_model_1`
- `P2PILOT_001__8X6B__main|9e6y|cluster_3_model_2`
- `P2PILOT_001__8X6B__main|9e6y|cluster_4_model_1`
- `P2PILOT_001__8X6B__main|9e6y|cluster_3_model_3`
- `P2PILOT_001__8X6B__main|9e6y|cluster_4_model_2`
- `P2PILOT_001__8X6B__main|9e6y|cluster_5_model_1`
- `P2PILOT_001__8X6B__main|9e6y|cluster_4_model_3`
- `P2PILOT_001__8X6B__main|9e6y|cluster_2_model_2`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_1_model_1`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_2_model_1`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_1_model_2`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_3_model_1`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_4_model_1`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_2_model_2`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_3_model_2`
- `P2PILOT_001__8X6B__replicate|8x6b|cluster_5_model_1`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_1_model_1`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_2_model_1`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_1_model_2`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_3_model_1`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_4_model_1`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_2_model_2`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_3_model_2`
- `P2PILOT_001__8X6B__replicate|9e6y|cluster_5_model_1`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_1_model_1`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_2_model_1`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_2_model_2`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_2_model_3`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_2_model_4`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_3_model_1`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_1_model_2`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_4_model_1`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_1_model_3`
- `P2PILOT_001__9E6Y__main|8x6b|cluster_5_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_1_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_2_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_2_model_2`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_2_model_3`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_2_model_4`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_3_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_1_model_2`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_4_model_1`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_1_model_3`
- `P2PILOT_001__9E6Y__main|9e6y|cluster_5_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_1_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_2_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_3_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_4_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_4_model_2`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_5_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_6_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_7_model_1`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_7_model_2`
- `P2PILOT_001__9E6Y__replicate|8x6b|cluster_2_model_2`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_1_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_2_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_3_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_4_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_4_model_2`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_5_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_6_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_7_model_1`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_7_model_2`
- `P2PILOT_001__9E6Y__replicate|9e6y|cluster_2_model_2`
- `P2PILOT_033__8X6B__main|8x6b|cluster_1_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_2_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_2_model_2`
- `P2PILOT_033__8X6B__main|8x6b|cluster_3_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_4_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_5_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_6_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_6_model_2`
- `P2PILOT_033__8X6B__main|8x6b|cluster_7_model_1`
- `P2PILOT_033__8X6B__main|8x6b|cluster_7_model_2`
- `P2PILOT_033__8X6B__main|9e6y|cluster_1_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_2_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_2_model_2`
- `P2PILOT_033__8X6B__main|9e6y|cluster_3_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_4_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_5_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_6_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_6_model_2`
- `P2PILOT_033__8X6B__main|9e6y|cluster_7_model_1`
- `P2PILOT_033__8X6B__main|9e6y|cluster_7_model_2`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_1_model_1`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_2_model_1`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_1_model_2`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_1_model_3`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_3_model_1`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_2_model_2`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_4_model_1`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_2_model_3`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_2_model_4`
- `P2PILOT_033__8X6B__replicate|8x6b|cluster_4_model_2`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_1_model_1`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_2_model_1`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_1_model_2`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_1_model_3`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_3_model_1`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_2_model_2`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_4_model_1`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_2_model_3`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_2_model_4`
- `P2PILOT_033__8X6B__replicate|9e6y|cluster_4_model_2`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_1_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_2_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_3_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_4_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_5_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_6_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_7_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_8_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_9_model_1`
- `P2PILOT_033__9E6Y__main|8x6b|cluster_10_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_1_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_2_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_3_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_4_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_5_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_6_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_7_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_8_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_9_model_1`
- `P2PILOT_033__9E6Y__main|9e6y|cluster_10_model_1`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_1_model_1`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_2_model_1`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_2_model_2`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_2_model_3`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_3_model_1`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_4_model_1`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_3_model_2`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_5_model_1`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_5_model_2`
- `P2PILOT_033__9E6Y__replicate|8x6b|cluster_6_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_1_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_2_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_2_model_2`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_2_model_3`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_3_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_4_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_3_model_2`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_5_model_1`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_5_model_2`
- `P2PILOT_033__9E6Y__replicate|9e6y|cluster_6_model_1`

## 科学处置

1. 保留当前 V1.1 scorer、postprocessor 和 smoke 输出不变，作为被拒绝版本的 provenance。
2. 新建版本化 protein-only scorer；不能在原文件上修补。
3. 用 11 条成功案例和匹配 decoy 重新校准连续指标、A/B/C/E 阈值与双 baseline 规则。
4. 重跑 8-run smoke，并重新执行独立双构象、重复性和数值闭环门。
5. 只有新版本通过后才运行/冻结 Pilot64 Gold；本报告中的 sensitivity class 不得直接训练。

## 证据与边界

- 行级 CSV：`/mnt/d/work/抗体/data/experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_1_hetatm_contamination_rows.csv`
- 机器审计 JSON：`/mnt/d/work/抗体/data/experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_1_hetatm_contamination_audit.json`
- CSV SHA256：`c0fcaabdc2760d93ca94f8e9291bf90b7a011e1dd0cd2f7820b567d492af2daa`
- JSON SHA256：`e016291bfa3b6dc611ff41f97521fc4286e38f262c3d45a3612a7649e7d34854`
- 当前 scorer SHA256：`c5e419daec19e6e38b6a52bfc63e0d6100c9c16f27b46a60235dc0f6a438982f`
- 当前 classifier SHA256：`c5f6f96d4821863dd14dc201807d8c863226876507df36a9e78b7a47e7df2654`
- rules SHA256：`60424c514d0e1c4f32bfec28631b969ed511c89babb4a73dcecf504e1e6a16a5`

> Read-only V1.1 contamination and sensitivity audit. Protein-only recomputation diagnoses HETATM-driven changes under the current V1.1 classification rules; it is not a V1.2 calibrated label, a corrected Docking Gold set, experimental binding truth, or blocking truth.
