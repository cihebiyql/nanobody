# Case 04：GSK4381562 / SRF813 / remzistotug 的 distinct epitope 机制详解

更新时间：2026-07-07

## 0. 为什么第四个案例看 GSK4381562 / SRF813

前面三个案例各自解决了一个问题：

```text
Case 01：COM701 / CPA.7.021 / Tab5
证明 PVRIG 上存在可药物化的 blocking epitope。

Case 02：PVRIG-20/30/38/39/151 / HR-151 VHH
证明 VHH 可以强阻断 PVRIG-PVRL2 表面界面。

Case 03：IBI352g4a
证明 Fc/NK context 会影响 PVRIG blocker 的体内功能输出。
```

第四个案例要解决的是另一个关键问题：

> 后续模型是不是只能围绕 Tab5/COM701 或 HR-151/151 这一类表位工作？

GSK4381562 / SRF813 的价值在于：公开资料把它描述为结合 PVRIG 的 **distinct epitope（不同表位）**，同时仍然阻断 CD112/PVRL2，并在预临床中增强 NK 和 T cell activation。

所以这个案例不是给我们一个残基级结构答案，而是给我们一个非常重要的建模约束：

```text
PVRIG blocker 可以有不止一种 epitope solution。
后续 docking / ranking 不能过拟合到 Tab5、HR-151 或 R95/I97 单一路线。
```

---

## 1. 分子身份：SRF813、GSK4381562、remzistotug 是什么关系

公开资料中这几个名字指向同一个 anti-PVRIG/CD112R 抗体项目：

```text
SRF813：Surface Oncology 阶段名称
GSK4381562：GSK 获得授权后的开发编号
remzistotug：药物通用名 / NCI 词条名称
```

NCATS/GInAS 对 remzistotug 的记录显示：

```text
protein type: monoclonal antibody
protein subtype: IgG1 | kappa
sequence origin: human
sequence type: complete
approval ID: 4U47PC3GYR
```

本地已把 GInAS 抓到的重链、轻链以及推断的 VH/VL 保存为：

```text
机制/data/sequences/PVRIG_case04_remzistotug_ginas_sequences.fasta
```

这对后续结构预测很有用，因为我们可以用它做：

```text
1. Fv / Fab 结构预测；
2. 与 PVRIG 的 docking 流程校对；
3. 与 Tab5 / HR-151 / 151 VHH 的表位多样性对照；
4. CDR 相似性和序列泄漏检查。
```

注意：这不是大会官方阳性序列，不能把它直接当作 SICBC 官方 positive。它是机制研究和流程校对的公开参考。

---

## 2. 它为什么重要：distinct epitope

Surface/GSK 公开新闻稿将 SRF813/GSK4381562 描述为：

```text
fully human IgG1 anti-PVRIG antibody
binds a distinct epitope on PVRIG
blocks CD112/PVRL2 interaction
promotes NK and T cell activation in preclinical studies
```

这里最重要的是 **distinct epitope**。

这句话的机制意义不是“它一定接触某个我们已知残基”，而是：

```text
它提示：PVRIG 上可产生 blocking 的抗体表位不止 COM701/Tab5/CPA.7.021 或 HR-151/151 一类。
```

换句话说，后续模型不能写成：

```text
越像 HR-151 越好
越像 Tab5 越好
越贴 R95/I97 越好
```

更合理的模型目标应该是：

```text
不同 CDR / paratope / pose
只要能占据、遮挡或变构干扰 PVRIG-PVRL2 functional interface
都可以被视为潜在 blocking solution。
```

---

## 3. 它和 COM701 / Tab5 / HR-151 的区别

### 3.1 和 COM701 / Tab5 的区别

COM701/CPA.7.021/Tab5 给我们的是 classic blocking antibody 逻辑：

```text
bind PVRIG
        ↓
block PVRIG-PVRL2
        ↓
解除 PVRIG checkpoint 抑制
```

SRF813/GSK4381562 同样保留 blocking 逻辑，但公开资料强调它的表位不同。

这意味着后续 docking 校对时，不应该要求 SRF813-like pose 完全复现 COM701/Tab5-like epitope。它应该作为 **anti-overfit control（反过拟合校对）**。

### 3.2 和 HR-151 / PVRIG-151 VHH 的区别

HR-151 是 VHH，靠单域抗体 CDR，尤其长 CDR3，可能形成突出 paratope。

SRF813/GSK4381562 是 IgG1 kappa full antibody。它的机制问题不再是 VHH CDR3 能不能插入界面，而是：

```text
IgG Fab 的 VH/VL paired paratope
        ↓
是否能在另一个表位方向上阻断 CD112/PVRL2
        ↓
同时 IgG1 Fc 是否有利于 NK/T cell context
```

所以它帮助我们把“PVRIG blocker”从单一 VHH 成功案例扩展到：

```text
VHH blocker
IgG4 blocker
IgG1 distinct-epitope blocker
Fc/NK-enhanced blocker
bispecific blocker
```

---

## 4. 关键机制：仍然是阻断 PVRIG-PVRL2，但下游多了一层 CD226 逻辑

NCI Drug Dictionary 对 remzistotug 的机制描述非常有用：

```text
remzistotug binds PVRIG/CD112R
        ↓
inhibits PVRIG-PVRL2 interaction
        ↓
may activate T lymphocytes and NK cells
        ↓
may promote PVRL2-CD226/DNAM-1 interaction
```

这说明 PVRIG blockade 的效果不只是“拆掉一个抑制性结合”，还可能把 PVRL2 从抑制性受体 PVRIG 一侧释放出来，让它更有机会和 activating receptor CD226/DNAM-1 发生功能关系。

可以理解成：

```text
阻断前：
PVRL2 binds PVRIG
        ↓
T/NK cell inhibition

阻断后：
anti-PVRIG blocks PVRIG-PVRL2
        ↓
PVRIG inhibitory signal 减弱
        ↓
PVRL2-CD226 activating axis 相对增强
        ↓
NK / T cell activation 上升
```

英文注释：

- **CD226 / DNAM-1** = activating receptor，能增强 T/NK 细胞功能。
- **ligand redirection** = 配体从抑制性受体占用中释放出来，转向或更有利于激活性通路。

这个逻辑对后续模型很重要：

```text
static docking 只能看 PVRIG-PVRL2 是否被遮挡；
但功能层还要理解 CD226/DNAM-1 轴可能被间接增强。
```

---

## 5. 功能证据：NK 和 T cell activation

AACR 2020 摘要题目和公开资料都指向同一件事：SRF813 是 fully human monoclonal antibody targeting CD112R/PVRIG，并增强 immune cell activation，在预临床模型中有抗肿瘤活性。

Surface/GSK 公开描述中也强调：

```text
blocks CD112/PVRL2 interaction
promotes NK cell activation
promotes T cell activation
preclinical in vivo anti-tumor activity
```

这和 Case 03 IBI352g4a 形成呼应：

```text
IBI352g4a：强调 IgG1/Fc-competent + NK activation
SRF813/GSK4381562：强调 distinct epitope + IgG1 + NK/T activation
```

因此 PVRIG 机制不是单纯 T cell checkpoint，也不是单纯 NK checkpoint，而是位于：

```text
DNAM-1 / TIGIT / CD96 / PVRIG axis
        ↓
T cell 和 NK cell 共同调控
```

对后续实验和模型来说，不能只盯 T cell readout，也不能只盯 docking score。

---

## 6. 临床状态必须谨慎：它是机制校对案例，不是临床成功案例

这里要非常谨慎。

公开临床/管线信息有不同层次：

```text
1. FDA 曾清除 GSK4381562 的 IND；
2. GSK/NCI 试验页面显示过 active-not-recruiting / closed-to-accrual 等状态；
3. 2025 年 Fierce Biotech 报道 GSK 放弃 CD226/PVRIG 轴剩余 phase 2 assets，包括 GSK4381562。
```

所以 Case 04 不能写成“临床已经成功”。更准确的定位是：

> SRF813/GSK4381562 是一个有公开 IND/临床进入证据、预临床功能证据和 distinct epitope 主张的机制校对案例；它对我们最有价值的是表位多样性和反过拟合，不是临床疗效背书。

对后续模型来说，这个区分很重要：

```text
机制成功 / 预临床功能案例 ≠ 临床疗效成功
```

---

## 7. 对后续结构预测和 docking 的直接价值

### 7.1 它是 anti-overfit control

如果我们后续只用 Tab5/HR-151/151 做校对，很容易让 docking/ranking 变成：

```text
越像已知阳性越好
```

这在比赛里反而危险，因为官方要求候选 CDR 与已知阳性保持足够差异。

SRF813/GSK4381562 提醒我们：

```text
可以存在不同表位、不同 paratope、不同 format 的 PVRIG blockers。
```

### 7.2 它提供 IgG/Fab 结构预测输入

本地已保存 remzistotug 的完整 heavy/light chain 和推断 VH/VL FASTA。后续可以做：

```text
VH/VL structure prediction
        ↓
Fab-PVRIG docking
        ↓
叠回 PVRL2
        ↓
检查是否遮挡 PVRL2 或靠近 functional interface
```

但注意：由于没有公开 SRF813-PVRIG complex structure，任何 docking 接触残基都必须标记为：

```text
model inference, not experimental epitope
```

### 7.3 它提醒我们不要把 R95/I97 当唯一答案

R95 是强 soft hint，I97 是弱 soft hint；但 SRF813/GSK4381562 的 distinct epitope 主张说明：

```text
候选不一定必须接触 R95/I97 才有可能 block。
```

更合理的判断是：

```text
候选是否遮挡 PVRIG-PVRL2 结合方式？
候选是否覆盖 consensus interface 的连续表面？
候选是否通过不同角度造成 PVRL2 steric occlusion？
```

---

## 8. 【重要标签】Case 04 后续 docking 校对标签

| 重要级别 | 标签 | 含义 | 对后续 docking / 结构预测的校对作用 |
| --- | --- | --- | --- |
| HIGH | `DISTINCT_EPITOPE_ALLOWED` | blocker 可以来自不同表位 | 不要求所有好 pose 都像 HR-151/Tab5 |
| HIGH | `BLOCKING_STILL_REQUIRED` | distinct epitope 仍然必须能阻断 CD112/PVRL2 | 远端 binder 不能因为 distinct 就被误判为好 blocker |
| HIGH | `ANTI_OVERFIT_CONTROL` | 该案例用于防止模型过拟合已知阳性 | 校对集要有 SRF813-like IgG/Fab family |
| HIGH | `IGG1_FORMAT_CONTEXT` | remzistotug 是 IgG1 kappa | docking 只解释 Fab，Fc/NK 需要单独评价 |
| MEDIUM | `CD226_AXIS_RELEVANT` | PVRIG blockade 可能增强 PVRL2-CD226/DNAM-1 激活轴 | 机制评分要记录 ligand redirection，不只看物理遮挡 |
| MEDIUM | `NK_AND_T_CELL_READOUT` | 公开资料提示 NK/T cell activation | 后续功能校对应保留 NK 和 T cell 两类 readout |
| MEDIUM | `PUBLIC_SEQUENCE_AVAILABLE` | NCATS/GInAS 有完整序列 | 可用于 Fv/Fab 预测和 docking 流程 sanity check |
| CAUTION | `NO_RESIDUE_LEVEL_EPITOPE` | 没有公开残基级表位/复合物结构 | docking 接触残基不能写成实验事实 |
| CAUTION | `CLINICAL_STATUS_NOT_MECHANISM_PROOF` | 后续临床开发状态不等于机制无效或有效 | 该案例只作为机制/设计校对，不作为临床成功背书 |

---

## 9. 对我们后续模型的具体要求

Case 04 加入后，后续 docking / ranking 流程至少应能区分四类结果：

```text
A. HR-151-like VHH blocker
B. Tab5/COM701-like IgG blocker
C. SRF813-like distinct epitope IgG blocker
D. remote PVRIG binder but non-blocker
```

真正应该保留的是 A/B/C，而不是 D。

因此评分不能只写：

```text
PVRIG binding score
```

而应该拆成：

```text
PVRIG binding score
PVRL2 occlusion / blocking score
interface coverage score
distinct-epitope allowance
positive-leakage penalty
Fab/VHH format compatibility
Fc/NK/CD226 mechanism annotation
```

一句话：

> SRF813/GSK4381562 告诉我们，模型要允许不同表位的 blocker，但不能放松“必须阻断 PVRIG-PVRL2”这个核心约束。

---

## 10. 当前缺口

当前仍缺少：

```text
1. SRF813-PVRIG 或 remzistotug-PVRIG 复合物结构；
2. 公开 residue-level epitope map；
3. 公开 alanine scanning / HDX / binning 详细表；
4. AACR poster/figure 中完整功能数值；
5. 统一 ANARCI/IMGT 编号后的 VH/VL CDR 表。
```

如果后续你能提供 poster、专利 PDF 或结构预测结果，我们应优先补：

```text
1. remzistotug VH/VL 的 IMGT CDR；
2. Fab-PVRIG docking pose；
3. 和 PVRL2 的 clash/occlusion 定量；
4. 是否接触 consensus interface 或形成 alternative blocking angle；
5. 与 Tab5/HR-151/151 的表位差异。
```

---

## 11. 本案例一句话结论

> GSK4381562 / SRF813 / remzistotug 是一个 distinct-epitope、IgG1-format anti-PVRIG 机制校对案例；它说明后续模型不能只复制 Tab5/HR-151 的表位逻辑，而要允许不同表位的 PVRIG blockers，同时继续坚持“必须阻断 PVRIG-PVRL2 / CD112”这一核心功能约束。

---

## 12. 来源和证据状态

| 证据 | 状态 | 链接或路径 |
| --- | --- | --- |
| Surface/GSK4381562 IND 新闻稿 | 可读摘要/搜索结果；Jina 当前 403 | https://www.biospace.com/surface-oncology-announces-fda-clearance-of-ind-application-for-gsk4381562-a-novel-antibody-targeting-pvrigsurface-to-receive-30-million-milestone-payment-upon-first-patient-treated-in-the-phase-1-study |
| AACR 2020 SRF813 摘要 | 可读摘要/搜索结果 | https://aacrjournals.org/cancerres/article/80/16_Supplement/4548/643519/Abstract-4548-SRF813-a-fully-human-monoclonal |
| NCI remzistotug Drug Dictionary | 可读，机制参考 | https://www.cancer.gov/publications/dictionaries/cancer-drug/def/remzistotug |
| NCATS/GInAS remzistotug 序列 | 已抓取并本地保存 | https://ginas.ncats.nih.gov/ginas/app/api/v1/substances/4U47PC3GYR |
| 本地 remzistotug FASTA | 已生成 | `机制/data/sequences/PVRIG_case04_remzistotug_ginas_sequences.fasta` |
| Case 04 evidence table | 已生成 | `机制/data/literature/PVRIG_case04_srf813_gsk4381562_evidence_table.csv` |
| Case 04 docking tags | 已生成 | `机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv` |
