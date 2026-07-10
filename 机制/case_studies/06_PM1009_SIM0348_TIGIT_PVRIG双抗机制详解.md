# Case 06: PM1009 / SIM0348 TIGIT-PVRIG 双抗机制详解

更新时间：2026-07-09

> 【重要结论】PM1009 和 SIM0348 继续证明：PVRIG 阳性机制不只是“一个 VHH/scFv 能阻断 PVRIG-PVRL2”，而是可以通过不同 IgG1 双抗 format，把 TIGIT/PVRIG 双检查点阻断、CD226/DNAM-1 共刺激恢复、Fc-mediated Treg killing 和 PD-1/PD-L1 联用场景整合起来。

---

## 1. 为什么把 PM1009 和 SIM0348 放在同一个案例

前一个 Case 05 的 SHR-2002 代表：

```text
anti-TIGIT IgG + N-terminal anti-PVRIG nanobody arm
```

PM1009 和 SIM0348 则给我们两个不同的 format 阳性参照：

```text
PM1009:
anti-TIGIT human IgG1 mAb + C-terminal anti-PVRIG scFv

SIM0348:
humanized IgG1-based TIGIT/PVRIG bispecific antibody
+ 强调 Fc-mediated killing of TIGIT/PVRIG-expressing Tregs
```

这三个案例放在一起，能告诉我们一个核心设计原则：

```text
同样是 TIGIT/PVRIG 双阻断，成功可以来自不同格式：
N端 VHH fusion
C端 scFv fusion
IgG1-based Fc-competent bispecific
```

所以后续筛选流程不能只问“PVRIG arm docking 好不好”，还要问：

```text
1. PVRIG arm 接到哪里；
2. linker 会不会挡住 paratope；
3. Fc 是 IgG1 还是 IgG4；
4. 是否需要 Treg depletion；
5. 是否依赖 PD-1/PD-L1 联用。
```

---

## 2. PM1009：C-terminal PVRIG scFv format

### 2.1 公开定位

NCI Drug Dictionary 把 PM1009 描述为 anti-TIGIT/anti-PVRIG bispecific antibody：一个 human IgG1 anti-TIGIT monoclonal antibody，C 端融合一个 targeting PVRIG 的 scFv。

ClinicalTrials.gov 的 NCT05607563 进一步把 PM1009 描述为 fully human anti-TIGIT x PVRIG bispecific antibody，含 wildtype IgG1 Fc，并且对两个靶点都有较高 monovalent affinity，可以同时结合 TIGIT 和 PVRIG。

英文注释：

```text
scFv = single-chain variable fragment，单链抗体片段，通常由 VH-linker-VL 构成。
C-terminal fusion = 把功能片段接在抗体链 C 端。
wildtype IgG1 Fc = 保留天然 IgG1 Fc 功能倾向，可能带来 FcγR 相关效应。
```

### 2.2 PM1009 的机制链条

PM1009 的机制可以写成：

```text
anti-TIGIT IgG1 arm binds TIGIT
        +
C-terminal anti-PVRIG scFv binds PVRIG
        ↓
blocks TIGIT-CD155/CD112 and PVRIG-CD112/PVRL2
        ↓
CD112/CD155 更倾向与 CD226/DNAM-1 形成共刺激信号
        ↓
CD8+ T cell / NK cell activation 增强
        ↓
immune-mediated tumor cell killing 增强
```

【重要标签：CD226_REBALANCING】

PM1009 的重点不是“两个 blocker 简单相加”，而是把 ligand 使用权从抑制性受体转回共刺激性 CD226/DNAM-1。

也就是说：

```text
阻断 TIGIT/PVRIG
    不是只减少 inhibitory signaling；
    也是把 CD112/CD155 从 immune brake 重新导向 immune accelerator。
```

### 2.3 对筛选流程的启发

PM1009 给我们的 format 校对点是：

```text
C-terminal anti-PVRIG scFv 是否仍然能接触 PVRIG；
scFv linker 与 IgG1 C端连接后是否影响 paratope 暴露；
IgG1 Fc 是否需要被保留，因为它可能参与更强免疫效应；
PVRIG arm 的 blocking pose 是否在 C-terminal fusion 后仍保留。
```

这和 SHR-2002 的 N-terminal nanobody fusion 不一样。后续如果你的筛选流程只看裸 VHH docking，就无法比较：

```text
N端 VHH format
C端 scFv format
VHH-Fc format
IgG1 Fc-competent BsAb format
```

---

## 3. SIM0348：IgG1 + Fc-mediated Treg killing

### 3.1 公开定位

NCI 把 SIM0348 描述为 humanized IgG1-based anti-TIGIT/anti-PVRIG bispecific antibody。它同时结合并抑制 TIGIT 和 PVRIG。

Simcere 2023 年公告进一步强调，SIM0348 是 humanized TIGIT/PVRIG bi-specific antibody injection，IgG1-based protein，可以阻断 CD155/TIGIT 和 CD112/PVRIG，并具有独特 Fc-mediated effector function。

### 3.2 SIM0348 和 PM1009 的关键区别

PM1009 和 SIM0348 都是 TIGIT/PVRIG 双抗，但 SIM0348 的突出点是：

```text
Fc-mediated killing of TIGIT-expressing Tregs
Fc-mediated killing of Tregs expressing both TIGIT and PVRIG
```

【重要标签：FC_MEDIATED_TREG_KILLING】

这说明 SIM0348 的机制不是单纯 checkpoint blockade：

```text
机制 1：TIGIT/PVRIG 双阻断
机制 2：CD226/DNAM-1 共刺激恢复
机制 3：IgG1 Fc 介导免疫抑制性 Treg 清除
```

这对后续筛选很重要：

```text
如果我们设计裸 VHH 或 Fc-silent VHH-Fc，
即使 blocking 很好，
也不会自动复现 SIM0348 的 Fc-mediated Treg killing 机制。
```

### 3.3 SIM0348 的功能证据

Simcere 公告给出 preclinical 方向：

```text
1. 促进 NK cells 对 human colorectal cancer cells 和 leukemia cells 的 killing；
2. 增强 antigen-specific CD8+ T cells 的 IFN-gamma secretion；
3. 效果高于 PVRIG 或 TIGIT monotherapy；
4. 与 anti-PD-L1 antibody 联用在模型中表现强。
```

Annals of Oncology 2025 年 163MO first-in-human phase I 摘要给出临床早期信号：

```text
NCT05718219
advanced solid tumors
SIM0348 monotherapy 或 SIM0348 + sintilimab
截至 2025-04-30 入组 49 人
MTD 未达到
组合治疗有初步 antitumor activity，尤其 heavily treated NSCLC 队列
selected doses 下 peripheral T cells 上 TIGIT/PVRIG receptor occupancy 接近完全
```

【重要标签：RECEPTOR_OCCUPANCY_GATE】

这说明：

```text
结构/亲和力/docking
        ↓
必须进一步转化成 receptor occupancy
        ↓
再转化成 T/NK function 和临床 activity signal
```

---

## 4. 这两个案例给筛选流程新增什么

### 4.1 新增 format branch

到 Case 06 为止，我们至少看到四种成功/半成功 format：

```text
裸 VHH / VHH-Fc：PVRIG-20/30/38/39/151, HR-151
N-terminal PVRIG nanobody fusion：SHR-2002
C-terminal PVRIG scFv fusion：PM1009
IgG1 Fc-competent BsAb：SIM0348
```

因此后续候选不要只输出一个 docking rank，而应标注：

```text
best_format_guess:
- naked_vhh
- vhh_fc
- bivalent_vhh
- n_terminal_nanobody_fusion
- c_terminal_scfv_fusion
- fc_competent_igg1_bispecific
- fc_silent_igg4_bispecific
```

### 4.2 新增 Fc 机制标签

```text
fc_mode:
- Fc-silent / IgG4-like: 更偏纯 checkpoint blockade
- IgG1 wildtype: 可能带来 FcγR engagement
- IgG1 Fc-competent + Treg killing: 类似 SIM0348 思路
```

这意味着：

```text
同一个 PVRIG arm，接在不同 Fc/format 上，功能输出可能完全不同。
```

### 4.3 新增 Treg/TME 机制标签

如果候选要学习 SIM0348 机制，需要考虑：

```text
TIGIT+ Treg abundance
TIGIT/PVRIG double-positive Treg abundance
NK/CD8 effector availability
CD112/CD155 ligand expression
PD-1/PD-L1 combination context
```

这已经超出普通 VHH docking，但对“阳性机制”非常重要。

---

## 5. 对 PVRIG VHH/候选的具体判断规则

如果你的筛选流程已经输出一批 PVRIG VHH，可以这样给每个候选加机制标签：

```text
1. blocking_core_score:
   是否覆盖 PVRIG-PVRL2 interface。

2. format_designability_score:
   是否适合接 Fc、IgG、双抗、二价 format。

3. c_terminal_scfv_compatibility:
   如果做 PM1009-like format，PVRIG paratope 在 C端 scFv 中是否可及。

4. n_terminal_vhh_compatibility:
   如果做 SHR-2002-like format，N端 VHH fusion 后是否仍暴露 CDR。

5. fc_effector_strategy:
   是否希望保留 IgG1 Fc effector 或采用 Fc-silent/IgG4。

6. tme_context_score:
   是否适合 TIGIT/PVRIG/Treg/NK/CD8 共表达环境。
```

最重要的筛选原则：

```text
如果目标是裸 VHH：
    优先 blocking_core_score + developability。

如果目标是 VHH-Fc：
    加入 Fc/linker accessibility 和二价几何。

如果目标是 TIGIT/PVRIG 双抗：
    必须加入 format_designability、dual-binding geometry、Fc strategy。

如果目标学习 SIM0348：
    必须把 Fc-mediated Treg killing 当成单独机制，而不是 docking score 的一部分。
```

---

## 6. 当前证据文件

```text
机制/data/literature/PVRIG_case06_pm1009_sim0348_evidence_table.csv
机制/data/literature/PVRIG_case06_pm1009_sim0348_calibration_tags.csv
机制/data/literature/sources/nci_pm1009_drug_dictionary.md
机制/data/literature/sources/nci_sim0348_drug_dictionary.md
机制/data/literature/sources/clinicaltrials_NCT05607563_PM1009.json
机制/data/literature/sources/simcere_SIM0348_FPI_20230403.md
机制/data/literature/sources/annals_SIM0348_163MO_2025.md
```

外部来源：

```text
NCI PM1009:
https://www.cancer.gov/publications/dictionaries/cancer-drug/def/anti-tigit-anti-pvrig-bispecific-antibody-pm1009

ClinicalTrials PM1009:
https://clinicaltrials.gov/study/NCT05607563

NCI SIM0348:
https://www.cancer.gov/publications/dictionaries/cancer-drug/def/anti-tigit-anti-pvrig-bispecific-antibody-sim0348

Simcere SIM0348 FPI announcement:
https://en.simcere.com/news/detail.aspx?mtt=337

Annals of Oncology SIM0348 163MO:
https://www.annalsofoncology.org/article/S0923-7534(25)05949-6/fulltext
```

---

## 7. 一句话总结

> 【重要总结】PM1009 和 SIM0348 说明，TIGIT/PVRIG 双抗成功机制至少有三层：第一层是 PVRIG-PVRL2 和 TIGIT-ligand 双阻断；第二层是 CD226/DNAM-1 共刺激恢复；第三层是 IgG1 Fc/format 带来的 Treg killing 或更强 TME 重塑。因此，后续筛选流程要把 PVRIG arm 的 blocking pose、format_designability、Fc strategy 和 TME context 分开评分。
