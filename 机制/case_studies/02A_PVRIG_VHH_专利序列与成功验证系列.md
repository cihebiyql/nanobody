# Case 02A: WO2021180205A1 中 PVRIG-20/30/38/39/151 VHH 专利序列与成功验证系列

更新时间：2026-07-07

> 【重要结论】不是拿不到专利，也不是 PVRIG-20/30/38/39/151 没有完整序列。WO2021180205A1 已经给出原始 VHH 表2和人源化 HCVR 表12-16。本轮已经把这些序列整理成 FASTA、mapping、CDR 表和用于后续结构预测/docking 的成功案例校准系列。

---

## 1. 本轮拿到的专利证据

主专利：

```text
WO2021180205A1 - PVRIG binding protein and its medical uses
Google Patents: https://patents.google.com/patent/WO2021180205A1/en
本地 PDF: 机制/data/patents/WO2021180205A1/WO2021180205A1.pdf
```

本轮使用的关键原图证据：

```text
机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000002.png
  - 表2：原始 PVRIG-20 / 30 / 38 / 39 / 151 HCVR 序列，SEQ ID NO:2-6

机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000003.png
机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000004.png
  - 表3：20/30/38/39/151 的 Kabat / Chothia / IMGT / AbM CDR 定义

机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000011.png
机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000012.png
  - 表12：20H1-20H5 人源化 HCVR，SEQ ID NO:75-79

机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000013.png
  - 表13：30H1-30H5 人源化 HCVR，SEQ ID NO:80-84

机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000014.png
机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000015.png
  - 表14：38H2/38H4/38H7/38H8/38H9 人源化 HCVR，SEQ ID NO:86-90

机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000016.png
  - 表15：39H1-39H5 人源化 HCVR，SEQ ID NO:91-95

机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000017.png
机制/data/patents/WO2021180205A1/google_patent_images/PCTCN2021080470-appb-000018.png
  - 表16：151H2/151H4/151H7/151H8/151H9 人源化 HCVR，SEQ ID NO:96-100
```

---

## 2. 已生成的可用文件

### 2.1 专利 VHH/HCVR FASTA

```text
机制/data/sequences/PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta
```

内容：

```text
30 条序列：
- 原始 camel VHH：PVRIG-20 / 30 / 38 / 39 / 151，共 5 条
- 人源化 HCVR：20H1-20H5，共 5 条
- 人源化 HCVR：30H1-30H5，共 5 条
- 人源化 HCVR：38H2/38H4/38H7/38H8/38H9，共 5 条
- 人源化 HCVR：39H1-39H5，共 5 条
- 人源化 HCVR：151H2/151H4/151H7/151H8/151H9，共 5 条
```

### 2.2 序列映射表

```text
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_sequence_mapping.csv
```

字段包括：

```text
molecule_name
family
seq_id_no
sequence_type
length
confidence
extraction_method
source_table
source_image
source_url
patent
sha256
notes
sequence
```

### 2.3 专利 CDR 参考表

```text
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_patent_cdr_reference.csv
```

用途：保留专利表3中 Kabat / IMGT 给出的家族 CDR，适合作为后续 docking 和相似性排除的人工参考。

### 2.4 ANARCI / IMGT CDR 表

```text
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_imgt_cdr_table.csv
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv
机制/data/literature/anarci/PVRIG_case02_vhh_20_30_38_39_151_anarci_imgt_H.csv
```

用途：和现有 validator 体系对齐，使用 IMGT 区间：

```text
CDR1: IMGT 27-38
CDR2: IMGT 56-65
CDR3: IMGT 105-117
```

【注意】ANARCI/IMGT 的插入位点排序与线性序列中的 CDR 展示可能不同；因此：

```text
- docking / 结构预测：用 FASTA 完整序列
- docking scorer / CDR range：用 raw_anarci_exact_cdr_table.csv 的 raw_anarci_imgt_cdr*_exact 和 cdr*_range
- 相似性排除：优先用 raw_anarci_exact_cdr_table.csv；旧 imgt_cdr_table.csv 只作展示/审计
- 人工机制解释：同时参考 patent_cdr_reference.csv
```

当前审计结论：旧 `imgt_cdr_table.csv` 的 `cdr3` 展示列与 raw ANARCI
column-order exact FASTA CDR3 在 30/30 条上不同；批量 docking 校准已经使用
raw ANARCI exact-match 范围，不使用该展示列作为执行输入。

### 2.5 成功案例校准系列

```text
机制/data/literature/PVRIG_case02_success_validation_series.csv
```

用途：给后续结构预测、docking、blocking-score 流程做阳性校准，而不是作为新设计候选。

---

## 3. 最重要的成功验证系列

> 【重要标签：SUCCESS_VALIDATION_SERIES】这些是“已知成功案例 / 阳性校准 / 泄漏排除参照”，不是我们自己的新设计。

| 优先级 | 分子 | SEQ ID | 为什么重要 | 建议用途 |
|---:|---|---:|---|---|
| 1 | PVRIG-151 / HR-151 | 6 | 原始系列中 blocking IC50 最强，且与官网 HR-151 阳性序列完全一致 | 官方阳性、docking 正对照、leakage 排除 |
| 2 | PVRIG-20 | 2 | 原始强 blocker，20H5 的 parent | parent-child 结构变化校对 |
| 3 | PVRIG-30 | 3 | 原始强 blocker，30H2 的 parent | parent-child 结构变化校对 |
| 4 | PVRIG-38 | 4 | 原始 blocker，CDR 家族与 20/39/151 不同 | 表位多样性校对 |
| 5 | PVRIG-39 | 5 | 原始强 blocker，39H2/39H4 的 parent | parent-child 结构变化校对 |
| 6 | 20H5 | 79 | 人源化系列中表18亲和力最强，Kd 6.98E-11 M | humanized high-affinity positive |
| 7 | 30H2 | 81 | 后续双抗 1708-30H2 的 PVRIG arm，Kd 1.92E-09 M | format-transfer control |
| 8 | 39H2 | 92 | 亚 nM humanized binder，Kd 6.92E-10 M，双抗 arm | strong humanized positive |
| 9 | 39H4 | 94 | 亚 nM humanized binder，Kd 4.82E-10 M | 39H2 近邻序列对照 |
| 10 | 151H7 | 98 | 151 family humanized arm，后续双抗 arm，Kd 1.20E-09 M | HR-151 humanized comparison |
| 11 | 151H8 | 99 | 151 family EVQL counterpart | N 端/framework sensitivity control |

---

## 4. 专利实验给出的关键成功证据

### 4.1 原始 20/30/38/39/151 都是 blocker，不只是 binder

专利实施例6检测抗 PVRIG 抗体阻断 human PVRIG 与 human PVRL2 的能力。表7给出 ELISA IC50：

```text
20:  1.18 nM
30:  1.11 nM
38:  0.93 nM
39:  0.76 nM
151: 0.37 nM
Tab5: 1.16 nM
IgG4: no blocking
```

【重要标签：BLOCKING_NOT_BINDING】

这说明 Case 02 的关键不是“它们能结合 PVRIG”，而是“这些 VHH/Fc 分子能阻断 PVRIG-PVRL2”。后续 docking 校对必须看：

```text
1. 是否贴近 PVRIG-PVRL2 interface；
2. 是否覆盖或空间遮挡 PVRL2 接触区域；
3. 是否由 CDR / CDR3 主导形成阻断面；
4. 是否能解释 151 > 39 > 38/30/20 的阻断强弱趋势。
```

### 4.2 原始 151 是 HR-151，且是最强 blocker

本地校验：

```text
PVRIG-151_HR151 patent sequence == positives/known_positive_antibodies.fasta 中 hr151_vhh
长度均为 127 aa
完全一致
```

【重要标签：OFFICIAL_POSITIVE_EQUALS_PATENT_151】

所以 HR-151 / PVRIG-151 应作为：

```text
- 官方阳性正对照
- structure prediction 正对照
- docking positive control
- CDR identity leakage exclusion 参照
```

但不能作为我们的设计模板直接改几个点。

### 4.3 人源化不是简单换 framework，而是保 CDR + 回突变/稳定性优化

专利实施例11说明：

```text
1. 先按 VHH 典型结构选择人 germline framework；
2. 替换 framework；
3. 保留 CDR（Kabat）；
4. 对埋藏残基、与 CDR 直接作用的残基、影响构象的残基做回复突变；
5. 对 CDR 区化学不稳定氨基酸残基优化；
6. 与 IgG4 Fc(S228P/F234A/L235A/K447A) 组合。
```

【重要标签：HUMANIZATION_IS_STRUCTURE_CONSTRAINED】

这对我们后续模型很关键：

```text
不能只让模型“改得更人源化”；
必须保留 CDR 构象、CDR-framework 支撑关系、界面阻断能力。
```

### 4.4 20 family 的 DDDY -> DEDY 是一个非常有价值的优化线索

原始 PVRIG-20 的专利表3 Kabat CDR3：

```text
GFKFDDDYCAPND
```

人源化 20H1-20H5 表12/正文给出的 CDR3：

```text
GFKFDEDYCAPND
```

【重要标签：CDR_STABILITY_OPTIMIZATION_HINT】

这可能对应专利中“CDR 区化学不稳定氨基酸残基优化”的实际操作。后续设计时不要机械保留原始 DDDY，而应把它当成：

```text
- 原始 parent：用于机制和 docking 校准；
- DEDY humanized：用于 developability 更好的成功案例校准。
```

---

## 5. 后续 docking / 模型筛选如何使用这批序列

### 5.1 推荐的校准顺序

```text
第一批结构预测：
PVRIG-151_HR151
PVRIG-20
PVRIG-30
PVRIG-38
PVRIG-39
20H5
30H2
39H2
39H4
151H7
151H8
```

### 5.2 推荐的判定标准

> 【重要标签：DOCKING_CALIBRATION_STANDARD】如果 docking 或评分流程不能把这些已知 blocker 解释成 interface-occluding binders，这个流程就不能直接用来筛最终候选。

校准时至少记录：

```text
1. 是否接近 PVRIG consensus interface；
2. 是否覆盖 core hotspot：R95 / G96 / R98 / W100 / F139 / E141 / W144 等；
3. CDR3 是否朝向 PVRIG-PVRL2 interface；
4. VHH 是否与 PVRL2 产生空间互斥；
5. 是否能区分 strong positive、weak/edge positive、non-blocking IgG4 negative；
6. 是否把 HR-151/151 与 20H5/39H2/39H4 排在合理位置。
```

### 5.3 不应该做的事

```text
不要把这些专利序列当作我们的新设计提交；
不要直接围绕 HR-151 或 20H5 做几个点突变后提交；
不要只看 binding score；
不要把 docking 总分当作 blocking score；
不要忽略 CDR identity < 80% 的比赛要求。
```

---

## 6. 本轮仍未完成的内容

```text
1. 还没有抽取 1708-20H5 / 1708-30H2 / 1708-39H2 / 1708-151H7 / 1708-151H8 的全长双特异性重链序列；
2. 还没有对这些 VHH 做结构预测；
3. 还没有把它们 docking 到 PVRIG；
4. 还没有把 docking pose 与 8X6B / 9E6Y 的 PVRIG-PVRL2 interface 做 steric occlusion 定量；
5. 还没有把 patent CDR 表、ANARCI CDR 表和官网 validator 的 identity 计算完全打通。
```

下一步建议：

```text
1. 先对 success_validation_series.csv 中 11 条做 NanoBodyBuilder2 / IgFold 结构预测；
2. 用 PVRIG_hotspot_set_v1.csv 作为 docking/hotspot 约束；
3. 计算每个 pose 对 PVRL2 的 steric occlusion；
4. 用 HR-151 / PVRIG-151 和 20H5 / 39H2 / 39H4 作为阳性校准；
5. 再决定是否抽取 1708-xx 双抗全长构型用于 TIGIT/PVRIG 联合机制校准。
```

---

## 7. 一句话总结

> 【重要总结】WO2021180205A1 已经给出 PVRIG-20/30/38/39/151 原始 VHH 以及多组人源化 HCVR。我们现在已经把它们整理成 30 条高置信专利序列，并挑出 11 条成功案例校准系列。后续应该用它们校对“结构预测 + docking + blocking 判断”流程，而不是把它们当作新候选提交。
