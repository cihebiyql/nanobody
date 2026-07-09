# PVRIG 成功抗体/纳米抗体案例机制研究 v1

更新时间：2026-07-06

## 0. 本文档解决什么问题

当前我们已经用 8X6B / 9E6Y 定义了 PVRIG-PVRL2 的结构接触 baseline。但仅看两个复合物结构还不够，因为真正成功的抗体/纳米抗体还必须回答：

```text
1. 它是不是只 bind PVRIG，还是能 block PVRIG-PVRL2？
2. 它是否真的激活 T/NK 细胞？
3. 它成功依赖哪个表位、哪种格式、哪种 Fc、哪种联用场景？
4. 它给后续 AI 模型提供什么可学习的机制标签？
```

因此本文档把公开资料中的成功或半成功案例拆成机制证据，而不是把它们当作可以直接照抄的序列来源。

## 1. 总结先行

我现在的判断是：PVRIG 方向的“成功”不是单一路径，而是至少有 5 条机制路线。

| 路线 | 代表案例 | 真正成功点 | 对我们后续模型的启发 |
| --- | --- | --- | --- |
| 单抗阻断 PVRIG-PVRL2 | COM701 / CPA.7.021 / Tab5 | 临床级别 anti-PVRIG blocker，机制明确 | blocking score 必须优先于普通 binding score |
| distinct epitope + IgG1 Fc | GSK4381562 / SRF813、IBI352g4a | 不同表位和 Fc 设计会改变 NK/T cell 功能 | 表位多样性和 Fc/format 是独立维度 |
| VHH / sdAb 阻断 | PVRIG-20/30/38/39/151，HR-151 | VHH 可做到 nM/sub-nM 结合和 nM 级阻断 | VHH 是合理主赛道，但不能只围绕 151 |
| TIGIT-PVRIG 双抗 | SHR-2002、PM1009、SIM0348 | 同时解除 DNAM 轴两个抑制分支 | PVRIG 单药可能不够，联用/双抗机制很重要 |
| 结构工程化 ligand trap | CD112RIVE | 用结构指导改造 CD112R 本身，提高 CD112 亲和力 | 证明结构界面可以被工程化，不限于抗体 |

最关键的一句话：

> 后续不是找“像 HR-151 的 VHH”，而是找“能用不同序列和合理格式复现 PVRIG-PVRL2 阻断机制”的分子。

## 2. 案例 A：COM701 / CPA.7.021 / Tab5 系列

### 2.1 公开定位

COM701 是 Compugen 的 anti-PVRIG 抗体，NCI 药物词典把它描述为靶向 PVRIG 的人源化单抗；其机制是结合 CTL 和 NK 细胞上的 PVRIG，阻断 PVRIG 与 PVRL2/CD112 的相互作用，从而解除 PVRIG 对 T/NK 细胞的抑制。

Compugen 官网还强调，COM701 来自其计算发现平台识别的 PVRIG 免疫检查点，目前围绕卵巢癌 maintenance 场景和与 PD-1/TIGIT 相关组合进行临床开发。

### 2.2 CPA.7.021 / Tab5 为什么重要

公开专利和后续论文把 COM701/benchmark 与 CPA.7.021 联系起来；大会官网给出的 Tab5 序列也与 CPA.7.021 系列高度相关。这个系列的价值不是“序列可抄”，而是：

```text
1. 它证明 PVRIG ECD 上存在可被 IgG 占据的阻断表位；
2. 它在细胞/生化竞争实验中表现为 strong blocker；
3. 它提示 R95/I97 附近是一些成功抗体的关键表位区域；
4. 它也暴露了 cynomolgus cross-reactivity 的问题。
```

### 2.3 关键机制证据

专利中 29 个 hybridoma 抗体的筛选显示，并不是所有 PVRIG binders 都是 blockers：其中有 20 个明确阻断 PVRIG-PVRL2，9 个不阻断。这个结论对我们非常关键：

```text
binding antibody != blocking antibody
```

在比较 CPA.7.021、CPA.7.002、CPA.7.005、CPA.7.050 的不同 assay orientation 时，CPA.7.021 被描述为最佳阻断抗体之一。这个信息说明：

```text
同一个抗体在不同竞争实验方向下阻断强度会变化；
真正要看的是它能不能在 PVRIG/PVRL2 真实竞争条件下稳定占住功能表位。
```

### 2.4 表位启发

Compugen 专利中的 cyno-to-human variant mapping 指出，S67、R95、I97 会影响部分 anti-human PVRIG 抗体的食蟹猴交叉反应；其中 CPA.7.021/CPA.7.028 被归为 R95/I97 相关表位组。

这与我们当前结构图谱吻合的是：

```text
R95：同时是 patent epitope hint 和 8X6B/9E6Y consensus interface residue。
I97：相邻，但结构支持弱于 R95。
S67：是专利 hint，但不在当前 4.5 A interface baseline。
```

所以后续模型里：

```text
R95 = 高权重 soft hotspot
I97 = 低/中权重 soft hotspot
S67 = 保存为表位线索，但不驱动阻断评分
```

## 3. 案例 B：GSK4381562 / SRF813

### 3.1 公开定位

GSK4381562 也叫 SRF813，是 Surface Oncology/GSK 方向的 fully human IgG1 anti-PVRIG antibody。公开资料称它结合 PVRIG 上 distinct epitope，并阻断 PVRIG 与 CD112/PVRL2 的相互作用；预临床上促进 NK 和 T cell activation。

### 3.2 为什么它对我们有价值

它的价值不是“临床已经证明一定成功”，而是给了一个设计原则：

```text
阻断 PVRIG-PVRL2 不一定只有 CPA.7.021/Tab5/HR-151 那一类表位。
```

也就是说，后续模型不能只把 R95/I97 周围当作唯一答案。应该允许多个 bin/epitope family，只要满足：

```text
1. 接触或覆盖 consensus interface；
2. 造成 PVRL2 结合角度/空间冲突；
3. 在功能实验中能提升 NK/T cell activation。
```

### 3.3 格式启发

GSK4381562 是 IgG1，区别于 COM701 的 Fc-reduced/IgG4 思路。这个差异和 IBI352g4a 的结果一起提示：

```text
PVRIG 抗体的成功不只是 paratope/epitope，还涉及 Fc 功能和免疫细胞场景。
```

对我们当前 VHH 工作来说，如果后续做 VHH-Fc fusion，Fc 不是“只延长半衰期”的尾巴，它可能直接影响 NK 细胞功能输出。

## 4. 案例 C：IBI352g4a

### 4.1 公开定位

IBI352g4a 是 Innovent 发表的 humanized IgG1 anti-PVRIG antibody。论文显示它结合 human PVRIG ECD，具有高亲和力，并能完全阻断 PVRIG-PVRL2。

关键数据：

```text
human PVRIG BLI Kd: 0.53 nM
human PVRIG/PVRL2 blocking IC50: 0.94 nM
cynoPVRIG Kd: 2.71 nM
```

### 4.2 它为什么成功

IBI352g4a 的特别点不是“它又是一个 blocker”，而是它系统证明了 NK cell 和 Fc engagement 的重要性。论文核心结论是：

```text
1. PVRIG blockade 主要先激活 NK cell；
2. T cell activation 更弱或更晚出现；
3. Fc effector function 对体内抗肿瘤效果很重要。
```

这说明如果后续我们只做无 Fc 的 VHH，可能会得到一个很好的 blocking molecule，但未必复现 IgG1 抗体在 NK 场景里的全部药效。

### 4.3 对模型的启发

后续模型要把机制标签拆开：

```text
binding affinity
blocking IC50
NK activation potential
T-cell activation potential
Fc/format contribution
species cross-reactivity
```

不要把这些混成一个 docking score。

## 5. 案例 D：HR-151 / PVRIG-151 / PVRIG-20/30/38/39 VHH 系列

### 5.1 公开定位

WO2021180205A1 公开了多个 PVRIG binding protein，包括 VHH/single-domain antibody，以及与 anti-TIGIT 抗体构建的双特异性抗体。大会官网给出的 HR-151 VHH 对应这一类阳性参考。

### 5.2 为什么这个系列重要

这个专利不是只给了一个 151，而是给了一组 VHH：

```text
PVRIG-20
PVRIG-30
PVRIG-38
PVRIG-39
PVRIG-151
```

它们在专利里的 PVRIG/PVRL2 阻断 IC50 大致在 nM 级，其中 151 的阻断 IC50 最强。亲和力表也显示 20、30、39、151 都达到 sub-nM 或低 nM 级别。

这说明：

```text
1. VHH 确实可以有效打 PVRIG-PVRL2 这种表面界面；
2. HR-151 不是唯一可行 VHH；
3. 20/30/38/39/151 之间很可能代表多个可行 paratope shape 或 developability tradeoff。
```

### 5.3 不要误读 151

专利的动物实验信息很有启发：PVRIG-151 单药在某个 A375 + human PBMC 小鼠模型里并没有明显优于对照；但与 TIGIT 方向结合，尤其 1708-151-IgG4 双抗，表现明显增强，甚至在该实验中显示强抑瘤。

这意味着：

```text
151 是强 blocker，但强 blocker 不等于强单药。
```

PVRIG biology 可能更依赖：

```text
1. TIGIT/PVRIG 共表达；
2. PVRL2/CD112 与 CD155/PVR 的 ligand context；
3. PD-1/TIGIT/PVRIG 三通路联动；
4. VHH 装配位置、价态、Fc format。
```

### 5.4 对我们最重要的启发

后续不要只做“HR-151 类似序列”。更好的做法是：

```text
1. 把 HR-151/151 作为 positive leakage 排除对象；
2. 把 20/30/38/39/151 当作不同 VHH 成功形态的机制参考；
3. 让模型寻找不同 CDR、不同 paratope，但仍覆盖 PVRIG-PVRL2 functional epitope；
4. 后续可考虑 VHH-Fc、二价 VHH、或 TIGIT-PVRIG 双抗格式，而不仅是裸 VHH。
```

## 6. 案例 E：SHR-2002 / TIGIT-8-PVRIG-30-IgG4

### 6.1 公开定位

2025 年 Molecular Cancer Therapeutics 论文报道了 co-blocking TIGIT and PVRIG 的双特异性抗体 SHR-2002。摘要显示，它通过把 anti-PVRIG nanobody 融合到 anti-TIGIT antibody 的 N 端来构建，能同时阻断 TIGIT/CD155 和 PVRIG/CD112。

关键结果包括：

```text
T cell activation 增加约 2.8 fold
NK cell cytotoxicity 增加约 1.8 fold
humanized PBMC mouse / transgenic mouse 模型中有抗肿瘤活性
食蟹猴重复给药 200 mg/kg 未见 dose-limiting toxicity
```

### 6.2 为什么它对“纳米抗体”特别重要

这个案例说明纳米抗体不一定最终以单体 VHH 形式出现；它也可以作为模块，被接到 IgG scaffold 上做双抗。

这里和 WO2021180205A1 里的 1708-30H2 / 1708-151H7 双抗路线是一致的：

```text
PVRIG nanobody arm + TIGIT antibody arm
        ↓
同时解除 PVRIG-PVRL2 和 TIGIT-CD155/CD112 抑制
        ↓
增强 T/NK cell activation
```

### 6.3 对我们模型的启发

如果后续只筛“最强 PVRIG binder”，可能会错过 format-level 成功因素。应该考虑：

```text
1. VHH 是否适合接到 IgG N 端或 C 端；
2. CDR 是否在 fusion 后仍暴露；
3. linker 长度是否允许同时结合两个 checkpoint；
4. IgG4 / IgG1 format 对 NK activation 的影响可能不同。
```

## 7. 案例 F：PM1009 和 SIM0348

### 7.1 PM1009

NCI 把 PM1009 描述为 anti-TIGIT IgG1 与 anti-PVRIG scFv 融合的双特异性抗体。其机制是同时抑制 TIGIT 和 PVRIG，并让 CD112/CD155 更倾向于通过 CD226 触发共刺激。

它不是 VHH，但对我们有机制价值：

```text
PVRIG arm 可以不是完整 IgG，也可以是 scFv / sdAb 模块；
双抗设计的核心是重塑 DNAM axis 的信号平衡。
```

### 7.2 SIM0348

NCI 把 SIM0348 描述为 humanized IgG1-based anti-TIGIT/anti-PVRIG bispecific antibody。它同时结合/抑制 TIGIT 和 PVRIG，并且还强调 Fc-mediated killing of TIGIT/PVRIG-expressing Tregs。

这进一步说明：

```text
PVRIG 成功案例越来越多不是单抗单靶点，而是 multi-axis / multi-effector 设计。
```

## 8. 案例 G：CD112RIVE / 结构指导 ligand trap

### 8.1 不是抗体，但非常重要

2025 年 Molecular Therapy 论文用 CD112-CD112R/PVRIG 结构做 structure-guided engineering，设计了更高亲和力的 CD112R variants。其中最高亲和力版本 CD112RIVE 可作为 soluble CD112 trap，阻断 CD112-CD112R 相互作用；这些变体还被放入 CAR/TCE 设计中增强对 CD112+ TNBC 细胞的 T cell activation 和 killing。

### 8.2 为什么它对我们重要

这说明：

```text
1. PVRIG-PVRL2/CD112 界面可以被结构工程化；
2. 关键不只是抗体 CDR，而是整个 interface 的 affinity tuning；
3. 9E6Y 这种结构不是只能画图，还能指导 mutant library 和 directed evolution。
```

对后续 AI 模型来说，这支持我们建立：

```text
interface residue priority
buried surface / contact density
ligand competition geometry
affinity-tuning residue map
```

而不是只跑黑箱 docking。

## 9. 这些案例共同说明什么

### 9.1 成功不是一个指标，而是一个链条

成功链条应该是：

```text
bind PVRIG ECD
    ↓
occupy functional interface
    ↓
block PVRIG-PVRL2/CD112
    ↓
restore CD226-biased activation context
    ↓
activate NK / CD8 T cells
    ↓
在合适 tumor context 中产生效应
```

### 9.2 表位不是唯一，但 functional interface 是主轴

目前至少能看到几种可能：

```text
1. R95/I97 相关表位：CPA.7.021/Tab5 类，有明确 patent mapping 支持。
2. 其他 distinct epitope：GSK4381562/SRF813 提示不同表位也能阻断。
3. VHH 小型 paratope：20/30/38/39/151 说明 VHH 可插入/覆盖表面界面。
4. engineered receptor trap：CD112RIVE 说明直接强化 receptor-ligand interface 也可成药。
```

因此我们后续应避免两个极端：

```text
错误 1：只打 R95/I97，忽略其他 functional epitope。
错误 2：只看整体 docking score，忽略是否真正竞争 PVRL2。
```

### 9.3 NK cell 是必须重点建模的生物学输出

IBI352g4a、Li et al. 2021、GSK4381562、SHR-2002 都指向 NK cell activation。后续模型如果只考虑 T cell checkpoint，会漏掉 PVRIG 重要特征。

建议后续标签至少包含：

```text
NK_activation_support
T_cell_activation_support
Fc_engagement_required_or_not
PVRL2_high_tumor_context
TIGIT_PD1_combination_context
```

## 10. 对后续模型/筛选的具体建议

### 10.1 机制特征不要只来自结构

建议未来每个候选分子都打这些标签：

```text
interface_coverage_score
R95_neighborhood_score
PVRL2_steric_clash_score
distinct_epitope_bonus
positive_CDR_leakage_penalty
VHH_fusion_compatibility_score
NK/Fc_context_flag
TIGIT_combination_potential
species_cross_reactivity_risk
```

### 10.2 VHH 方向的具体建议

```text
1. 不要直接改 HR-151；HR-151 是查重阳性参考。
2. 同时参考 PVRIG-20/30/38/39/151 的 CDR 长度、VHH 框架和阻断数据。
3. 把 PVRIG-30 纳入重点参考，因为 SHR-2002 使用的是 PVRIG-30 类 nanobody arm。
4. 对 VHH 设计要提前考虑是否可 Fc fusion 或双抗化。
5. 单体 VHH 的 blocking 好，不代表体内单药强；后续需要 format-aware ranking。
```

### 10.3 下一步机制挖掘优先级

```text
优先级 1：把 PVRIG-20/30/38/39/151 的 CDR 和结构预测加入相似性排除/形态参考。
优先级 2：整理 CPA.7.021 / CPA.7.050 / CHA blockers 的 epitope bin 和阻断强度。
优先级 3：为 8X6B/9E6Y 加 delta SASA、氢键、盐桥、疏水接触。
优先级 4：调研 GSK4381562/SRF813 和 NM1F 是否公开更多 epitope/binning 数据。
优先级 5：把 SHR-2002、PM1009、SIM0348 的格式信息纳入 future-format 设计，不影响第一轮 VHH scaffold 但影响后续路线。
```

## 11. 来源索引

- COM701 / NCI Drug Dictionary: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/anti-pvrig-monoclonal-antibody-com701
- Compugen COM701 pipeline page: https://cgen.com/our-science/pipeline/com701-anti-pvrig-antibody/default.aspx
- GSK4381562 / SRF813 BioSpace press release: https://www.biospace.com/surface-oncology-announces-fda-clearance-of-ind-application-for-gsk4381562-a-novel-antibody-targeting-pvrigsurface-to-receive-30-million-milestone-payment-upon-first-patient-treated-in-the-phase-1-study
- IBI352g4a paper: https://link.springer.com/article/10.1007/s00262-024-03671-z
- PVRIG VHH / WO2021180205A1 patent: https://patents.google.com/patent/WO2021180205A1/en
- Compugen anti-PVRIG patent / EP3258951B1: https://patents.google.com/patent/EP3258951B1/en
- SHR-2002 PubMed: https://pubmed.ncbi.nlm.nih.gov/39851063/
- SHR-2002 AACR/Molecular Cancer Therapeutics: https://aacrjournals.org/mct/article/24/5/664/761971/Co-blocking-TIGIT-and-PVRIG-Using-a-Novel
- PM1009 / NCI Drug Dictionary: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/anti-tigit-anti-pvrig-bispecific-antibody-pm1009
- SIM0348 / NCI Drug Dictionary: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/anti-tigit-anti-pvrig-bispecific-antibody-sim0348
- CD112RIVE / structure-guided CD112R variants: https://www.sciencedirect.com/science/article/pii/S1525001625003119
- PVRIG/Nectin-2 structural basis: https://www.sciencedirect.com/science/article/pii/S0969212624000947
- PVRIG NK cell blockade paper: https://link.springer.com/article/10.1186/s13045-021-01112-3


---

## 附：Case 05 详细拆解已完成

```text
机制/case_studies/05_SHR2002_TIGIT_PVRIG双抗机制详解.md
机制/data/literature/PVRIG_case05_shr2002_tigit_pvrig_bispecific_evidence_table.csv
机制/data/literature/PVRIG_case05_shr2002_docking_calibration_tags.csv
```

关键词：SHR-2002、TIGIT-8-PVRIG-30-IgG4、PVRIG nanobody arm、N-terminal fusion、dual checkpoint blockade、format_designability_score。
