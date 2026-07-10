# Case 05: SHR-2002 / TIGIT-8-PVRIG-30-IgG4 双抗机制详解

更新时间：2026-07-08

> 【重要结论】SHR-2002 的价值不是告诉我们“再找一个更强 PVRIG binder”，而是证明 PVRIG VHH 可以作为可移植模块，被放进 TIGIT/PVRIG 双抗格式里，把 PVRIG-PVRL2 阻断机制升级成 TIGIT/PVRIG 双检查点共阻断机制。

---

## 1. 这个案例是什么

SHR-2002 是 2025 年 Molecular Cancer Therapeutics 论文报道的 TIGIT/PVRIG bispecific antibody。论文题目是：

```text
Co-blocking TIGIT and PVRIG Using a Novel Bispecific Antibody Enhances Antitumor Immunity
PMID: 39851063
DOI: 10.1158/1535-7163.MCT-23-0614
```

公开摘要给出的核心信息：

```text
1. TIGIT 和 PVRIG 在 activated T cells 和 NK cells 上共表达；
2. 二者共同参与 tumor immune evasion；
3. SHR-2002 通过把 anti-PVRIG nanobody 融合到 anti-TIGIT antibody 的 N 端构建；
4. 它同时阻断 TIGIT-CD155 和 PVRIG-CD112；
5. 它增强 T-cell activation 和 NK-cell cytotoxicity；
6. 在 humanized PBMC mouse 和 transgenic mouse 模型中有抗肿瘤活性；
7. 食蟹猴重复给药安全性/PK 信号较好。
```

英文注释：

```text
bispecific antibody / BsAb = 双特异性抗体，一个分子同时识别两个靶点。
co-blocking = 同时阻断两条抑制通路。
format-level success = 分子格式本身带来的成功，不只是 CDR 或表位成功。
```

---

## 2. 它为什么是“阳性机制”

这个案例满足我们定义的阳性机制链条：

```text
PVRIG arm binds PVRIG
        ↓
blocks PVRIG-CD112/PVRL2
        ↓
TIGIT arm blocks TIGIT-CD155
        ↓
解除两条 DNAM/TIGIT/PVRIG 轴上的抑制信号
        ↓
T cell activation 增强
NK cytotoxicity 增强
        ↓
in vivo antitumor activity
```

所以它不是一个单纯的结构/结合案例，而是：

```text
binding + blocking + immune-cell function + in vivo activity + cyno translation
```

这比单个 PVRIG docking pose 更接近真实药物成功逻辑。

---

## 3. 最关键的实验证据

### 3.1 双靶点生物学背景

PubMed 摘要指出，TIGIT 和 PVRIG 是 activated T cells / NK cells 上共表达的 immune checkpoints，并参与 tumor immune evasion。

【机制含义】

```text
PVRIG 单独阻断可能不足；
如果 TIGIT 同时在同一批 T/NK cells 上提供抑制信号，双阻断更容易看到功能输出。
```

这解释了为什么前面的 VHH 151 虽然是强 blocker，但单药模型里未必总能产生最强体内效果。

### 3.2 分子格式

公开摘要说明，SHR-2002 是把 anti-PVRIG nanobody 融合到 anti-TIGIT antibody 的 N terminus。

【重要标签：N_TERMINAL_VHH_DISPLAY】

这对后续建模很关键：

```text
PVRIG VHH arm 的 CDR 必须在 IgG fusion 后仍然暴露；
linker / N端位置 / IgG scaffold 不能遮挡 PVRIG paratope；
单体 VHH docking 好，不代表 fusion 后仍然能同时结合两个靶点。
```

### 3.3 功能输出

PubMed 摘要报告：

```text
T-cell activation: 2.8-fold increase, P < 0.05
NK-cell cytotoxicity: 1.8-fold increase, P < 0.05
```

【重要标签：T_NK_FUNCTION_GATE】

这说明一个 PVRIG 阳性机制要至少经过三层门槛：

```text
1. PVRIG binding；
2. PVRIG-CD112 blocking；
3. T/NK cell function recovery。
```

只看 binding 或 docking，不能证明它是功能阳性。

### 3.4 体内与联用

摘要还报告，SHR-2002 在 humanized PBMC-reconstituted 和 transgenic mouse 模型中有抗肿瘤活性，并且可以与 anti-PD-1 或 anti-PD-L1 联用。

【重要标签：COMBINATION_CONTEXT】

这给我们的筛选流程一个提醒：

```text
PVRIG blocker 的真实价值可能取决于 PD-1/TIGIT/PVRIG context；
后续模型可以先筛 PVRIG blocker，但最终解释时不能假装 PVRIG 是唯一免疫刹车。
```

### 3.5 食蟹猴转化信号

摘要报告，在 cynomolgus monkey 中做 PK/safety 评估，四次重复给药 200 mg/kg 未观察到 dose-limiting toxicity。

【重要标签：CYNO_TRANSLATION】

这说明成功案例不仅要看 human PVRIG，还要看：

```text
human/cyno cross-reactivity；
Fc/format 在非人灵长类中的耐受性；
构建体是否有可开发性问题。
```

---

## 4. 它和 PVRIG-30 / HR-151 专利 VHH 的关系

SHR-2002 文献公开语境中出现 `TIGIT-8-PVRIG-30-IgG4` / `PVRIG-30-IgG4` 这一类 parental construct 说法；我们本地已经从 WO2021180205A1 中整理了 PVRIG-30 与 30H2 等 VHH/HCVR 序列。

本地相关文件：

```text
机制/data/sequences/PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_sequence_mapping.csv
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_imgt_cdr_table.csv
机制/data/sequences/PVRIG_case05_shr2002_related_pvrig_arms.fasta
```

【谨慎边界】

```text
可以把 PVRIG-30 / 30H2 当作 PVRIG arm 的本地校准序列；
但除非拿到 SHR-2002 论文/专利的完整 sequence listing，不能把本地 PVRIG-30 序列直接等同于 SHR-2002 的最终临床/候选序列。
```

也就是说：

```text
用于机制校对：可以；
用于声明 exact SHR-2002 sequence：不可以；
用于新设计提交：不可以。
```

---

## 5. 对我们后续筛选流程的启发

### 5.1 不能只筛 PVRIG binding

SHR-2002 证明：

```text
最好的 PVRIG arm 未必单独成为最佳药物；
它可能需要被放在正确 format 中，和 TIGIT/PD-1/PD-L1 机制配合。
```

所以后续筛选可以分层：

```text
Layer 1: VHH 是否能 bind PVRIG；
Layer 2: 是否能 block PVRIG-PVRL2/CD112；
Layer 3: 是否适合 VHH-Fc / IgG fusion；
Layer 4: 是否能在 TIGIT/PVRIG 或 PD-1/TIGIT/PVRIG context 中发挥功能。
```

### 5.2 对 docking 的校对标准

【重要标签：DUAL_CHECKPOINT_NOT_SINGLE_BINDER】

如果你后续 docking PVRIG-30 / 30H2 / 151H7 等 PVRIG arms，需要检查：

```text
1. VHH 是否仍然能覆盖 PVRIG-PVRL2 interface；
2. 在 fusion 到 IgG N 端之后，CDR 是否仍暴露；
3. VHH 的 N/C 端方向是否适合 linker；
4. 是否存在 linker 太短导致 TIGIT arm 和 PVRIG arm 互相干扰；
5. 是否能和 anti-TIGIT arm 同时结合，不产生 steric clash；
6. IgG4 format 是否更适合避免不希望的 Fc 过强效应。
```

### 5.3 对候选排序的修正

后续如果你已经搭了筛选流程，Case 05 应该给候选加一个额外标签：

```text
format_designability_score
```

这个分数不同于 developability，也不同于 docking：

```text
format_designability_score =
    VHH 端点方向是否适合 fusion
  + CDR 是否远离 fusion/linker 干扰
  + N端/C端 fusion 后 paratope 是否仍可及
  + 是否保留 PVRIG-PVRL2 blocking pose
  + 是否适合二价/Fc/双抗构型
```

更直白地说：

```text
binding / docking score：
这个 VHH 单独存在时，能不能贴住 PVRIG。

format_designability_score：
这个 VHH 被接到 Fc、IgG、二价 VHH 或 TIGIT/PVRIG 双抗里以后，
还能不能用同样正确的姿势贴住 PVRIG，并继续阻断 PVRIG-PVRL2。
```

可以把 VHH 理解成一个“钩子”，Fc/IgG/双抗理解成“钩子后面的杆子和支架”。钩子本身能勾住目标还不够，装到支架上以后还要满足：方向对、不被支架挡住、仍然能勾到 PVRIG-PVRL2 的功能界面。

### 5.3.1 VHH 端点方向是否适合 fusion

VHH 是一条单链，有 N 端和 C 端。做 VHH-Fc 或双抗时，通常要从 N 端或 C 端接 linker。

好的情况：

```text
CDR/paratope 朝向 PVRIG interface
N端或C端朝外
linker / Fc / IgG scaffold 在背面或侧面
```

坏的情况：

```text
N端或C端刚好朝向 PVRIG interface
接上 linker/Fc 后，大结构挤进结合面
VHH 原本的 blocking pose 被拉歪或挡住
```

所以这项看的是：VHH 的可连接端点是否在空间上适合接东西。

### 5.3.2 CDR 是否远离 linker/IgG scaffold 干扰

VHH 真正识别 PVRIG 的位置主要是 CDR，尤其 CDR3。linker 或 IgG scaffold 如果太靠近 CDR，可能造成：

```text
1. 物理遮挡 CDR；
2. 限制 CDR 摆动；
3. 让原来能覆盖 PVRIG-PVRL2 interface 的 loop 变成侧向接触；
4. 让 blocker 退化成普通 binder。
```

所以这项看的是：融合后 CDR/paratope 是否还露在外面，而不是被自己的 scaffold 挡住。

### 5.3.3 N端/C端 fusion 后 paratope 是否仍可及

`paratope` 是 VHH 上接触抗原的表面；`epitope` 是 PVRIG 上被识别的表面。

这项要问：

```text
单体 VHH docking 时 paratope 能接触 PVRIG；
接上 Fc/IgG/双抗后，这个 paratope 是否仍然能接触 PVRIG？
```

如果 fusion 后 paratope 被埋住、朝向 IgG scaffold、或被 linker 拉到错误方向，这个 VHH 即使单体 docking 很好，也不适合做后续药物 format。

### 5.3.4 是否保留 PVRIG-PVRL2 blocking pose

这是最核心的一项。我们的目标不是普通 PVRIG binder，而是 blocker。

好的 pose 应该是：

```text
VHH 占住或遮挡 PVRIG-PVRL2 / CD112 接触面
        ↓
PVRL2 不能再贴到 PVRIG 上
```

坏的 pose 是：

```text
VHH 仍然结合 PVRIG
但接触位置偏到侧面
PVRL2 仍然可以结合
```

因此，format_designability 必须检查 fusion 后是否还保持“阻断姿势”，而不是只保持“结合姿势”。

### 5.3.5 是否适合二价/Fc/双抗构型

后续真实分子可能不是裸 VHH，而是：

```text
VHH-Fc
二价 VHH
双 VHH
VHH 接 IgG N 端或 C 端
TIGIT-PVRIG 双抗
PVRIG-PD1 / PVRIG-PDL1 组合格式
```

不同格式会引入不同空间限制。比如 TIGIT/PVRIG 双抗还要问：

```text
1. PVRIG arm 能不能接触 PVRIG；
2. TIGIT arm 能不能接触 TIGIT；
3. 两个 arm 是否能同时工作；
4. linker 长度是否够；
5. 两个靶点结合时有没有 steric clash；
6. Fc 是 IgG1 还是 IgG4，是否需要保留/削弱 effector function。
```

所以，如果一个 VHH 单体 docking 很好，但 CDR 靠近 N端 linker 或 fusion 后很容易被 IgG scaffold 挡住，它不应该排得太高。

### 5.3.6 可以落地成的粗评分

第一版不需要很复杂，可以先这样拆：

```text
format_designability_score =
0.25 x terminus_orientation_score
+ 0.20 x linker_clearance_score
+ 0.20 x paratope_accessibility_score
+ 0.25 x blocking_pose_retention_score
+ 0.10 x multivalent_format_score
```

对应含义：

| 子分数 | 看什么 | 好的表现 |
|---|---|---|
| terminus_orientation_score | N/C 端朝向 | 端点朝外，不朝向 PVRIG interface |
| linker_clearance_score | linker/Fc 是否靠近 CDR | CDR 与 linker/Fc 距离足够远 |
| paratope_accessibility_score | CDR/paratope 是否暴露 | CDR1/2/3 仍然可接触 PVRIG |
| blocking_pose_retention_score | fusion 后是否还挡 PVRL2 | 仍覆盖 PVRIG-PVRL2 interface |
| multivalent_format_score | 是否适合 Fc/二价/双抗 | 两个 arm 不互相打架，linker 方向合理 |

最短总结：

> format_designability_score 评价的不是“这个 VHH 能不能结合 PVRIG”，而是“这个 VHH 被做成 VHH-Fc、二价 VHH、IgG fusion 或 TIGIT/PVRIG 双抗后，还能不能保持原来的 PVRIG-PVRL2 阻断姿势，并且不被 linker/Fc/IgG scaffold 挡住”。

---

## 6. 推荐作为流程校对的本地序列

```text
机制/data/sequences/PVRIG_case05_shr2002_related_pvrig_arms.fasta
```

包含：

```text
PVRIG-30        # 原始 PVRIG-30 VHH，SEQ ID NO:3
30H2            # humanized 30-family HCVR，SEQ ID NO:81
PVRIG-151_HR151 # 官方 HR-151 / 专利 151，SEQ ID NO:6
151H7           # humanized 151-family HCVR，SEQ ID NO:98
```

推荐校对方式：

```text
1. 先预测单体 VHH 结构；
2. docking 到 PVRIG consensus interface；
3. 检查是否能 sterically occlude PVRL2；
4. 再模拟 N-terminal fusion/linker 方向；
5. 检查 fusion 后 CDR 是否仍可及；
6. 最后才考虑 TIGIT/PVRIG 双抗几何。
```

---

## 7. 当前证据文件

```text
机制/data/literature/PVRIG_case05_shr2002_tigit_pvrig_bispecific_evidence_table.csv
机制/data/literature/PVRIG_case05_shr2002_docking_calibration_tags.csv
机制/data/literature/sources/pubmed_39851063_shr2002_esummary.json
机制/data/literature/sources/pubmed_39851063_shr2002.xml
机制/data/sequences/PVRIG_case05_shr2002_related_pvrig_arms.fasta
```

外部来源：

```text
PubMed PMID 39851063
https://pubmed.ncbi.nlm.nih.gov/39851063/

AACR / Molecular Cancer Therapeutics DOI
https://doi.org/10.1158/1535-7163.MCT-23-0614

AACR Figshare supplement page
https://aacr.figshare.com/articles/dataset/Supplementary_Table_S2_from_Co-blocking_TIGIT_and_PVRIG_Using_a_Novel_Bispecific_Antibody_Enhances_Antitumor_Immunity/32709856
```

---

## 8. 一句话总结

> 【重要总结】SHR-2002 告诉我们：PVRIG 阳性机制不止是“VHH 能 bind/block PVRIG”，还包括“这个 VHH 是否能作为一个可移植模块，在 IgG4 / 双抗 format 中保持表位遮挡能力，并与 TIGIT blockade 共同放大 T/NK cell 功能”。因此，后续筛选流程应该新增 format_designability 和 dual-checkpoint context，而不是只靠 PVRIG docking 分数。
