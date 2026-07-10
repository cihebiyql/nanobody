# PVRIG-PVRL2 机制可视化与当前结论包

## 这个文件夹是什么

这是当前 PVRIG-PVRL2 结合机制探究的独立分享包，重点是看清楚：

1. PVRIG 和 PVRL2/Nectin-2 是怎么贴合的；
2. 哪些 PVRIG 残基是两个结构共同支持的核心界面残基；
3. R95 / I97 / S67 这些专利表位线索到底落在什么位置；
4. 后续如果搭建 AI/打分模型，应该围绕哪些机制约束，而不是直接做 docking 或最终抗体生成。

这个包不是最终候选抗体包，也不包含 Top 50 设计。

## 当前在线查看器

当前 Panel 服务未关闭，仍在运行：

```text
http://localhost:5007/pvrig_panel_viewer
```

如果后续需要重新启动：

```bash
cd /mnt/d/work/抗体
panel serve 机制/visualization/pvrig_panel_viewer.py --show --port 5007
```

## 推荐打开方式

### 方式 1：PyMOL 会话，最推荐

```bash
cd /mnt/d/work/抗体
pymol 机制/visualization/pvrig_pvrl2_mechanism_view.pse
```

### 方式 2：PyMOL 脚本

如果想重新生成视图：

```bash
cd /mnt/d/work/抗体/机制
pymol visualization/pvrig_pvrl2_mechanism_view_portable.pml
```

### 方式 3：浏览器 HTML 备选

打开：

```text
机制/visualization/pvrig_pvrl2_mechanism_view.html
```

这个 HTML 依赖 3Dmol.js CDN，适合快速看，但不如 PyMOL 会话完整。

## 文件结构

```text
机制/
├── README.md
├── PVRIG_PVRL2_机制当前结论.md
├── data/structures/
│   ├── 8X6B.pdb
│   ├── 9E6Y.pdb
│   ├── PVRIG_hotspot_set_v1.csv
│   ├── PVRIG_key_contact_residues_v1.csv
│   ├── PVRIG_consensus_interface_residues.csv
│   ├── PVRIG_soft_hint_structure_mapping.csv
│   ├── PVRIG_ligand_contact_pairs_8X6B.csv
│   └── PVRIG_ligand_contact_pairs_9E6Y.csv
├── figures/
│   ├── pvrig_pvrl2_interface_overlay.png
│   ├── pvrig_pvrl2_8x6b_interface.png
│   └── pvrig_pvrl2_9e6y_interface.png
├── reports/
│   └── pvrig_pvrl2_binding_mechanism_visual_notes.md
├── visualization/
│   ├── pvrig_pvrl2_mechanism_view.pse
│   ├── pvrig_pvrl2_mechanism_view.pml
│   ├── pvrig_pvrl2_mechanism_view_portable.pml
│   ├── pvrig_pvrl2_mechanism_view.html
│   └── pvrig_panel_viewer.py
└── official_reference/
    ├── SICBC_抗体赛道官方信息摘录.md
    └── 后续机制研究挖掘清单.md
```

## 图例

- PVRIG：青蓝色 / 蓝色
- PVRL2/Nectin-2：灰色
- core hotspots：橙色，两个结构共同支持的 PVRIG-PVRL2 interface residues
- secondary hotspots：黄色，单结构支持的 interface residues
- R95：洋红色，强 soft hint
- I97：粉色，弱 soft hint
- S67：蓝灰色，当前不用于 Phase I 机制评分
- 红色虚线：最近的 PVRIG-PVRL2 重原子接触

## 快速结论

- 当前最可靠的机制约束不是某一个单点，而是 PVRIG-PVRL2 的两结构共识表面。
- `PVRIG_hotspot_set_v1.csv` 把这个表面拆成 21 个 core hotspots、2 个 secondary hotspots、3 个 soft hints。
- R95 是最值得优先关注的 soft hint，因为它同时是 patent hint 和 consensus interface residue。
- I97 处在相邻区域，但结构支持弱于 R95。
- S67 可以作为表位线索保存，但不应驱动当前机制评分。
- 后续模型应该围绕“是否占据/干扰 PVRIG-PVRL2 共识界面”建模，而不是只追求普通 binding score。


## 新增：成功案例机制研究

```text
机制/success_cases/PVRIG成功案例机制研究_v1.md
机制/success_cases/来源索引_成功案例.md
机制/data/literature/PVRIG_success_case_evidence_matrix.csv
```

这部分补充了 COM701、GSK4381562/SRF813、IBI352g4a、HR-151/PVRIG-151 VHH、PVRIG-30/SHR-2002、PM1009、SIM0348、CD112RIVE 等案例，重点分析它们为什么能阻断或激活免疫，而不是只看 8X6B/9E6Y 两个结构。


## 新增：逐个真实案例机制拆解

```text
机制/case_studies/README.md
机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md
```

第一例已经拆解 COM701 / CPA.7.021 / Tab5，重点说明 clinical-stage anti-PVRIG blocker 如何连接到官方阳性参考、R95/I97 表位线索、以及 binder 与 blocker 的区别。


## 新增：第二例 VHH / 纳米抗体机制拆解

```text
机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_evidence_table.csv
机制/data/literature/PVRIG_case02_vhh_docking_calibration_tags.csv
```

第二例已经拆解 PVRIG-20/30/38/39/151 与官方 HR-151 VHH，重点说明 VHH 为什么可以强阻断 PVRIG-PVRL2、为什么 151 强但不能只盯 151、以及 VHH-Fc / TIGIT-PVRIG 双抗 format 为什么是机制成功的一部分。文档末尾新增了 `【重要标签】VHH 结合机制与后续 docking 校对标签`，用于后续结构预测和 docking 流程校对。


## 新增：Case 02A 专利序列与成功验证系列

```text
机制/case_studies/02A_PVRIG_VHH_专利序列与成功验证系列.md
机制/data/sequences/PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_sequence_mapping.csv
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_patent_cdr_reference.csv
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_imgt_cdr_table.csv
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv
机制/data/literature/PVRIG_case02_success_validation_series.csv
```

本轮已经从 WO2021180205A1 的专利表格原图整理出 PVRIG-20/30/38/39/151 原始 VHH 和 20H/30H/38H/39H/151H 人源化 HCVR，共 30 条高置信序列。推荐把其中 11 条作为结构预测、docking 和 blocking 判断流程的成功案例校准系列；这些序列是阳性参照/流程校准/相似性排除对象，不是我们的新设计候选。

执行提示：docking scorer / CDR range 请使用
`PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv` 的
`raw_anarci_imgt_cdr*_exact` 和 `cdr*_range` 字段；旧
`imgt_cdr_table.csv` 保留为展示/审计表，不作为执行输入。


## 新增：第三例 Fc/NK 机制拆解

```text
机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md
机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv
```

第三例已经拆解 IBI352g4a，重点说明 Fc-competent IgG1 anti-PVRIG 为什么能把 PVRIG-PVRL2 blocking 转化为更强 NK activation 和体内抗肿瘤效果；它提醒后续模型不能把 binding、blocking、Fc format、NK context 混成一个 docking 分数。


## 新增：第四例 distinct epitope 机制拆解

```text
机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md
机制/data/literature/PVRIG_case04_srf813_gsk4381562_evidence_table.csv
机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv
机制/data/sequences/PVRIG_case04_remzistotug_ginas_sequences.fasta
```

第四例已经拆解 GSK4381562 / SRF813 / remzistotug，重点说明 distinct epitope 为什么能作为反过拟合校对案例：后续模型要允许不同表位的 PVRIG blockers，但不能放松 PVRIG-PVRL2 / CD112 blocking 这个核心功能约束。


## 新增：第五例 TIGIT/PVRIG 双抗机制拆解

```text
机制/case_studies/05_SHR2002_TIGIT_PVRIG双抗机制详解.md
机制/data/literature/PVRIG_case05_shr2002_tigit_pvrig_bispecific_evidence_table.csv
机制/data/literature/PVRIG_case05_shr2002_docking_calibration_tags.csv
机制/data/sequences/PVRIG_case05_shr2002_related_pvrig_arms.fasta
机制/data/literature/sources/pubmed_39851063_shr2002.xml
```

第五例已经拆解 SHR-2002 / TIGIT-8-PVRIG-30-IgG4，重点说明 PVRIG VHH 不只是单体 blocker，也可以作为 anti-TIGIT IgG 的 N 端 nanobody arm，在双抗 format 中同时阻断 TIGIT-CD155 和 PVRIG-CD112，从而增强 T cell activation 与 NK cytotoxicity。这个案例给后续筛选流程新增 `format_designability_score` 和 `dual-checkpoint context` 两个机制维度。


## 新增：第六例 PM1009 / SIM0348 双抗机制拆解

```text
机制/case_studies/06_PM1009_SIM0348_TIGIT_PVRIG双抗机制详解.md
机制/data/literature/PVRIG_case06_pm1009_sim0348_evidence_table.csv
机制/data/literature/PVRIG_case06_pm1009_sim0348_calibration_tags.csv
机制/data/literature/sources/nci_pm1009_drug_dictionary.md
机制/data/literature/sources/nci_sim0348_drug_dictionary.md
机制/data/literature/sources/clinicaltrials_NCT05607563_PM1009.json
机制/data/literature/sources/simcere_SIM0348_FPI_20230403.md
机制/data/literature/sources/annals_SIM0348_163MO_2025.md
```

第六例已经拆解 PM1009 / SIM0348，重点说明 TIGIT/PVRIG 双抗不仅有 dual checkpoint blockade，还可能通过 CD226/DNAM-1 共刺激恢复、IgG1 Fc effector、以及 Fc-mediated Treg killing 改变 TME。这个案例把候选筛选从“PVRIG arm docking”进一步扩展到 `Fc strategy`、`Treg/TME context`、`C-terminal scFv compatibility` 等机制维度。
