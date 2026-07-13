# RFantibody-PVRIG 1,024 条候选：HADDOCK 分数与阻断几何分析

> 生成时间：`2026-07-13T15:14:54.053079+00:00`

## 1. 一句话结论

这 1,024 条序列都完成了 HADDOCK3，但不能据此宣称任何一条已经能阻断 PVRIG-PVRL2。
计算上有 47 条候选至少出现 1 个 8X6B/9E6Y 双参考一致的 `CONSENSUS_BLOCKER_LIKE_A` pose；
其中只有 1 条在 4/4 个 pose 上都为双参考 A。然而，这 47 条全部没有通过正式的三 seed RF2 独立恢复门槛，
所以当前最合适的结论是“有 blocker-like 几何、值得优先实验”，而不是“已经证明能阻断”。

## 2. 数据完整性与统计口径

- 候选：1,024 条 exact-unique VHH。
- HADDOCK selected models：8,606 个。
- 双参考 baseline 行：8,192，即 1,024 × 4 pose × 2 reference。
- 去重后的前 4 pose：4,096。
- 本流程是按 PVRIG-PVRL2 界面热点引导的受约束 docking，不是 blind docking；它检验的是目标表位条件下的 pose 兼容性。
- 9E6Y 是同一 8X6B-guided pose 的 reference-overlay scoring，不是独立第二轮 docking。
- HADDOCK 分数越负通常表示在该 scoring function 下更有利，但不是 Kd、IC50 或阻断率。

## 3. HADDOCK 分数分布

| 口径 | n | min | P5 | P25 | median | P75 | P95 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 全部 selected models | 8,606 | -116.95 | -86.37 | -71.45 | -61.23 | -51.03 | -36.44 | 133.14 |
| 每候选前 4 pose | 4,096 | -116.95 | -90.92 | -78.44 | -69.32 | -61.07 | -49.17 | -23.10 |
| 每候选 best score | 1,024 | -116.95 | -98.68 | -86.76 | -78.90 | -71.45 | -60.95 | -44.36 |

每候选 best score 的中位数是 `-78.90`；最负值为 `-116.949`。
其中 42 条 best score ≤ -100，159 条 ≤ -90，464 条 ≤ -80。
但最负分候选不一定是双参考 blocker-like，因此不能按 HADDOCK 分数单轴截断。

按 consensus class 看，分数中位数为：

| consensus class | pose 数 | HADDOCK median | min | max |
|---|---:|---:|---:|---:|
| `BLOCKER_PLAUSIBLE_B` | 2,491 | -69.21 | -115.91 | -25.79 |
| `CONSENSUS_BLOCKER_LIKE_A` | 63 | -79.81 | -104.84 | -54.88 |
| `EVIDENCE_INFERENCE_ONLY_E` | 320 | -60.04 | -92.23 | -23.10 |
| `SINGLE_BASELINE_BLOCKER_RECHECK` | 1,222 | -71.45 | -116.95 | -34.99 |

仅用 HADDOCK score 区分双参考 A 与其余 pose 的 AUC 约为 `0.740`；若把双参考 A 与单参考 recheck 合并为强几何组，AUC 仅约 `0.574`。
这说明分数和阻断几何有关，但远不足以替代热点/遮挡判定。

## 4. 双参考阻断几何

`BLOCKER_LIKE_A` 的规则阈值为：热点重叠 ≥14、总 PVRL2 遮挡 ≥500、CDR3 遮挡 ≥100、CDR3 遮挡比例 ≥0.15。
这些阈值定义的是计算分类，不是生物学真值。

| reference | BLOCKER_LIKE_A | BLOCKER_PLAUSIBLE_B | EVIDENCE_ONLY_E |
|---|---:|---:|---:|
| 8X6B | 1,282 | 2,462 | 352 |
| 9E6Y overlay | 66 | 3,325 | 705 |

8X6B 的 A 比例为 `31.30%`，9E6Y overlay 只有 `1.61%`。
这种明显不对称说明 9E6Y 是严格的跨构象过滤器，也说明多数 8X6B A pose 并不稳健。

| pose consensus | pose 数 | 占 4,096 pose | 涉及候选数 |
|---|---:|---:|---:|
| `CONSENSUS_BLOCKER_LIKE_A` | 63 | 1.54% | 47 |
| `SINGLE_BASELINE_BLOCKER_RECHECK` | 1,222 | 29.83% | 465 |
| `BLOCKER_PLAUSIBLE_B` | 2,491 | 60.82% | 841 |
| `EVIDENCE_INFERENCE_ONLY_E` | 320 | 7.81% | 169 |

候选级互斥分层：

- Tier 1：至少一个双参考 A，`47` 条。
- Tier 2：没有双参考 A，但至少一个单参考 A，`424` 条。
- Tier 3：只有 plausible B，`533` 条。
- Tier 4：只有 evidence-only，`20` 条。

47 条 Tier 1 中，A-pose 数量分布为：35 条有 1/4、9 条有 2/4、2 条有 3/4、1 条有 4/4。
多 pose 一致性比单个偶然 pose 更值得优先。

## 5. RF2 独立恢复与证据冲突

- 全体正式三 seed RF2 pass：`4` / 1,024。
- 至少一个双参考 A：`47` / 1,024。
- 同时满足双参考 A 与正式 RF2 pass：`0`。

这不是说 47 条一定不结合；RF2 fail 在本项目里明确只作为 QC，不能直接变成负标签。
但它表示最强 docking 几何没有得到独立 complex-pose 模型的支持，因此整体证据仍然偏弱。

## 6. 多样化 Top 20 计算候选

以下排名只代表 docking/blocker-geometry 实验优先级。它优先考虑双参考 A pose 数、单参考支持、跨参考最弱阈值余量和 HADDOCK 分数，
并按 near-CDR3 family、backbone 和 arm 做贪心去冗余。完整序列见 `reports/top20_diverse_blocker_geometry_panel.tsv`。

| rank | candidate_id | A/4 | 单参/4 | best HADDOCK | 代表 pose | 弱侧热点 | 弱侧总遮挡 | 弱侧 CDR3 | 弱侧比例 | CDR3 | RF2 |
|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| 1 | `PVRIG_RFAb_v2_P2_qkg_L_bb006_mpn00` | 4 | 0 | -88.58 | -88.58 | 15 | 760 | 123 | 0.162 | `GSSTTLDPADYTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 2 | `PVRIG_RFAb_v2_P5_qrg_L_bb004_mpn01` | 3 | 1 | -102.05 | -102.05 | 15 | 705 | 114 | 0.161 | `GGFIDPSDQTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 3 | `PVRIG_RFAb_v2_P2_ekg_S_bb005_mpn02` | 3 | 0 | -79.45 | -79.45 | 15 | 658 | 103 | 0.155 | `APAYSSSFQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 4 | `PVRIG_RFAb_v2_P2_qkg_L_bb003_mpn00` | 2 | 2 | -95.93 | -81.94 | 15 | 757 | 141 | 0.186 | `GPSSSLLPGTYSY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 5 | `PVRIG_RFAb_v2_P4_qrg_L_bb000_mpn00` | 2 | 2 | -95.60 | -95.60 | 15 | 637 | 125 | 0.196 | `GPGFYESTKQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 6 | `PVRIG_RFAb_v2_P1_ekg_L_bb003_mpn00` | 2 | 2 | -95.37 | -95.37 | 15 | 746 | 128 | 0.172 | `GASSSLNPGDYGY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 7 | `PVRIG_RFAb_v2_P4_ekg_L_bb005_mpn02` | 1 | 3 | -102.25 | -98.62 | 14 | 767 | 170 | 0.222 | `GYDTDASIDPDYYTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 8 | `PVRIG_RFAb_v2_P3_qrg_L_bb001_mpn00` | 1 | 3 | -96.84 | -76.49 | 14 | 697 | 106 | 0.152 | `GLEDSTQESSYSY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 9 | `PVRIG_RFAb_v2_P2_qrg_L_bb007_mpn01` | 1 | 3 | -95.29 | -95.29 | 14 | 785 | 160 | 0.204 | `QAGQNTLNPDEYQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 10 | `PVRIG_RFAb_v2_P2_qrg_L_bb004_mpn01` | 1 | 3 | -90.67 | -88.79 | 14 | 725 | 111 | 0.151 | `GEGFAEEDQQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 11 | `PVRIG_RFAb_v2_P4_ekg_L_bb004_mpn01` | 1 | 3 | -88.80 | -88.80 | 14 | 688 | 122 | 0.177 | `GTGSEPEEKQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 12 | `PVRIG_RFAb_v2_P3_qrg_L_bb006_mpn02` | 1 | 3 | -87.75 | -86.65 | 14 | 788 | 133 | 0.169 | `GPAISLDPSLYSY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 13 | `PVRIG_RFAb_v2_P4_qkg_L_bb004_mpn00` | 1 | 2 | -79.64 | -79.64 | 15 | 760 | 121 | 0.153 | `GSSDGPENKTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 14 | `PVRIG_RFAb_v2_P4_qrg_L_bb002_mpn02` | 1 | 2 | -75.88 | -72.08 | 14 | 810 | 130 | 0.160 | `GNLLEPQSYTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 15 | `PVRIG_RFAb_v2_P5_ekg_L_bb001_mpn01` | 1 | 2 | -66.21 | -62.41 | 14 | 799 | 138 | 0.173 | `GSTASSNPSAYTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 16 | `PVRIG_RFAb_v2_P3_ekg_L_bb002_mpn02` | 1 | 1 | -90.45 | -90.45 | 14 | 602 | 124 | 0.206 | `GVGFEPQFHTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 17 | `PVRIG_RFAb_v2_P2_ekg_L_bb006_mpn01` | 1 | 1 | -74.00 | -74.00 | 14 | 624 | 103 | 0.163 | `GLDSSLDPEDYQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 18 | `PVRIG_RFAb_v2_P5_ekg_L_bb003_mpn02` | 1 | 0 | -79.81 | -79.81 | 14 | 731 | 139 | 0.190 | `GITDSINPGDYTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 19 | `PVRIG_RFAb_v2_P3_qrg_L_bb007_mpn02` | 1 | 2 | -89.61 | -79.56 | 14 | 677 | 107 | 0.156 | `HPLAASLNPDAYTY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |
| 20 | `PVRIG_RFAb_v2_P4_ekg_L_bb007_mpn01` | 1 | 2 | -75.59 | -66.76 | 14 | 790 | 152 | 0.192 | `SGTYANLNPDLYQY` | `FORMAL_MULTI_SEED_FAIL_COMPLETE` |

### 当前最强 docking-geometry 候选

`PVRIG_RFAb_v2_P2_qkg_L_bb006_mpn00` 在 4/4 个 pose 上均为双参考 A；best HADDOCK 为 `-88.5811`。
其代表 pose 在两参考中较弱一侧仍有热点 `15`、总遮挡 `760`、CDR3 遮挡 `123`、CDR3 比例 `0.1618`。
但其 RF2 状态为 `FORMAL_MULTI_SEED_FAIL_COMPLETE`，best interaction PAE 为 `15.22`，
因此应标记为“高 docking-geometry 优先级、未获正交结构确认”。

## 7. 能否达到阻断效果

当前不能回答“能”。更准确的结论是：

1. 47 条候选在至少一个 pose 上满足双参考 blocker-like 几何，值得进入实验；
2. 只有 12 条在至少 2/4 pose 上稳定满足双参考 A，只有 3 条达到至少 3/4；
3. 没有任何 Tier 1 候选同时通过正式三 seed RF2 恢复；
4. 这批数据没有实验 binder label，1,024 条均为 `binder_axis_status=deferred`、`binder_label=unknown`；
5. 所以目前既不能证明它们结合 PVRIG，也不能证明它们阻断 PVRIG-PVRL2。

建议把 Tier 1 多样化 Top 12-24 送入实验，而不是把 1,024 条或所有低 HADDOCK 分数序列都当成 blocker。

## 8. 最小实验闭环

1. 表达与可开发性：小量表达、SEC/UPLC、MS、DSF，先排除聚集和异常降解。
2. PVRIG binding：ELISA 初筛后用 BLI/SPR 测 kon、koff、Kd；不结合者不能解释阻断。
3. 直接 competition：BLI/SPR 或 plate competition 测 PVRIG-PVRL2/CD112，输出 competition % 与 IC50。
4. 表位验证：PVRIG alanine scan、cross-blocking 或 HDX-MS，确认 R95/K135/F139/E141-G142/S143-W144 区域。
5. 功能实验：PVRIG/CD112R reporter 或免疫细胞共培养，确认功能恢复。
6. 对照：已知 blocker、非阻断 PVRIG binder、irrelevant VHH、无 VHH 四类对照必须齐全。

## 9. 数据质量提醒

`docking_pose_features.tsv` 中有 `12` 行 `buried_surface_area=-999999` sentinel。
它们不在用于双参考分类的前 4 pose 中，但训练模型前应转成 missing value，不能作为真实负 BSA 数值。
另外，当前只有 train/validation 两路 split，没有独立 test split；不能用这批数据自证泛化。

## 10. 输出文件

- `reports/docking_score_blocker_summary.json`：机器可读统计。
- `reports/ranked_blocker_geometry_candidates.tsv`：1,024 条候选完整排序及全序列。
- `reports/top20_diverse_blocker_geometry_panel.tsv`：去冗余 Top 20 及全序列。
- `scripts/analyze_docking_blocker_scores.py`：可复现统计脚本。
