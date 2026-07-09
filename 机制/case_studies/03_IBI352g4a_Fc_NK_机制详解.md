# Case 03：IBI352g4a / Fc-competent anti-PVRIG 的 NK 机制详解

更新时间：2026-07-07

## 0. 为什么第三个案例看 IBI352g4a

前两个案例分别说明了两件事：

```text
Case 01：COM701 / CPA.7.021 / Tab5
证明 PVRIG 上存在可药物化的 blocking epitope。

Case 02：PVRIG-20/30/38/39/151 / HR-151 VHH
证明 VHH / nanobody 也能强结合并阻断 PVRIG-PVRL2。
```

第三个案例要回答另一个更靠近药效的问题：

> 如果一个抗体已经能高亲和结合 PVRIG，也能阻断 PVRIG-PVRL2，为什么还要关心 Fc、NK cell 和体内模型？

IBI352g4a 的价值就在这里。它不是给我们一个新的 PVRIG-PVRL2 复合物结构，而是告诉我们：

```text
PVRIG blocker 的成功不只取决于 Fab / CDR 能不能挡住 PVRL2，
还取决于抗体 format 是否能把 NK 细胞真正拉起来。
```

英文注释：

- **Fc-competent antibody** = Fc 区保留效应功能、能结合 Fc receptor 的抗体。
- **Fc engagement / FcγR coengagement** = 抗体 Fc 区同时结合免疫细胞上的 Fcγ receptor，增强细胞激活。
- **CD16a / FcγRIIIA** = NK 细胞上重要 Fc receptor，通常更偏好 IgG1，而不是 IgG4。
- **NK activation** = NK 细胞被激活，表现为 CD107a、CD137、Granzyme B、IFNγ、perforin 等功能标志上升。

---

## 1. 分子身份：IBI352g4a 是什么

IBI352g4a 是 Innovent Biologics 报道的 humanized anti-PVRIG monoclonal antibody。

论文中给出的关键信息是：

```text
来源：murine clone ch44G1
人源化方式：CDR grafting / human germline framework replacement
最终格式：humanized IgG1 anti-PVRIG antibody
靶点：human PVRIG extracellular domain
对照抗体：BMK，即用 COM701/CPA.7.021 序列制备的人源化 IgG4 anti-PVRIG benchmark
```

这里的重点不是“IBI352g4a 比 COM701 一定更好”，而是它们提出了一个机制问题：

```text
COM701 / BMK：IgG4，Fc effector function 弱
IBI352g4a：IgG1，Fc effector function 完整
        ↓
同样打 PVRIG，体内免疫效应是否会不同？
```

这对我们后续设计很重要。因为如果我们最终只提交裸 VHH，它主要考验 PVRIG binding / blocking；如果后续考虑 VHH-Fc、IgG、双抗或多价形式，就必须把 Fc/NK 机制纳入评价。

---

## 2. 第一层成功：它先是一个真正的 PVRIG-PVRL2 blocker

IBI352g4a 首先满足基本门槛：强结合 PVRIG，并阻断 PVRIG-PVRL2。

论文报告的核心数值：

| 指标 | 数值 | 机制含义 |
| --- | ---: | --- |
| human PVRIG BLI Kd | 0.53 nM | 高亲和 PVRIG 结合 |
| human PVRIG cell binding EC50 | 2.03 nM | 在细胞表面 PVRIG 上也能结合 |
| human PVRIG-PVRL2 blocking IC50 | 0.94 nM | 能有效阻断配体 PVRL2 |
| cynoPVRIG BLI Kd | 2.71 nM | 保留食蟹猴交叉反应性 |
| cynoPVRIG cell binding EC50 | 7.42 nM | 具备非人灵长类开发基础 |

所以它仍然符合我们第一阶段定义的 blocking-oriented 标准：

```text
bind PVRIG ECD
        ↓
block PVRIG-PVRL2 ligand interaction
        ↓
解除或削弱 PVRIG 免疫抑制
```

但 IBI352g4a 案例的真正洞察不止于此。

---

## 3. 第二层成功：它显示 PVRIG blockade 更偏向先激活 NK，而不是直接强推 T cell

IBI352g4a 论文做了 NK 和 T cell 的并行功能实验。

### 3.1 NK 侧

他们使用 purified NK cells + K562 tumor cells 的 coculture 系统。K562 表达较高 PVRL2，因此适合观察 PVRIG-PVRL2 轴对 NK 杀伤的抑制。

论文中观察到：

```text
IBI352g4a treatment
        ↓
CD107a+ NK cells 增加
CD137+ NK cells 增加
K562 tumor cell death 增加
NK-mediated killing EC50 = 0.075 nM
```

这里 CD107a 是 degranulation marker，代表 NK 细胞释放杀伤颗粒；CD137 是 activation marker，代表 NK 激活状态增强。

机制解释：

```text
K562 tumor cell 上有 PVRL2
NK cell 上有 PVRIG
        ↓
PVRIG-PVRL2 结合抑制 NK
        ↓
IBI352g4a 阻断 PVRIG-PVRL2
        ↓
NK degranulation / activation / killing 上升
```

### 3.2 T cell 侧

同一篇论文又做了 CMV-specific T cell activation、CD25/CD69 activation、T cell proliferation、cytotoxic mediator 等实验。

结果方向非常明确：

```text
IBI352g4a 对体外 T cell activation / proliferation / direct cytotoxic readout 的促进很弱或接近阴性对照。
```

这不是说 PVRIG 与 T cell 无关，而是说在这个实验系统中，PVRIG antibody 的即时强效 readout 更像是 NK-driven。

这给我们的机制分层带来一个重要修正：

```text
PVRIG blocker 的第一性目标：阻断 PVRIG-PVRL2
但体内药效 readout：可能更依赖 NK cell context，而不是单纯 T cell assay
```

---

## 4. 第三层成功：体内模型说明“有 NK 的模型”和“只有 T cell 的模型”结论不同

IBI352g4a 论文比较了两类人源化模型：

```text
B-NDG hIL15 humanized model：有更好的 NK + T cell 重建
NOG PBMC model：更偏 T cell-only reconstitution，NK 支持不足
```

结果方向是：

```text
IBI352g4a 在 B-NDG hIL15 模型中有强抗肿瘤效果；
在 NK 支持不足的 NOG 模型中效果较弱。
```

这说明一个关键问题：

> 如果评价体系没有 NK 细胞或没有足够 FcγR context，可能低估 Fc-competent PVRIG blocker 的真实潜力。

所以后续如果我们搭模型，不要只用“PVRIG binding score + PVRL2 blocking score”就假装能预测体内药效。至少要把机制拆成两层：

```text
分子层：PVRIG-PVRL2 interface blocking
细胞层：NK/T cell context + FcγR coengagement + tumor PVRL2 expression
```

---

## 5. 第四层成功：PVRIG blockade 可能先激活 NK，再带动 T cell

论文还用 surrogate anti-PVRIG mAb 在 CT26 tumor model 中做了机制观察。

他们看了第一次给药后和第二次给药后的 tumor-infiltrating lymphocytes。

方向可以概括为：

```text
第一次给药后：
NK cell number / CD107a activation 上升更明显；
CD8+ T cell 总量没有立即显著变化。

第二次给药后：
CD8+ T cell 增加；
Granzyme B / CD107a / perforin 等 T cell cytotoxic markers 上升。
```

这给出一个很有价值的时间顺序假说：

```text
PVRIG blockade
        ↓
早期 NK activation
        ↓
肿瘤杀伤与局部炎症环境改变
        ↓
后续 CD8+ T cell recruitment / activation / cytotoxicity 上升
```

英文注释：

- **tumor-infiltrating lymphocytes, TILs** = 浸润到肿瘤组织里的免疫细胞。
- **depletion experiment** = 用抗体去除某类细胞，观察药效是否消失，用来判断该细胞是否必要。

论文中的 depletion experiment 也支持这个判断：NK cell depletion 会削弱或取消 anti-PVRIG 的治疗效果；CD8+ T cell depletion 也有类似趋势，但结合 NOG 模型结果，NK 的重要性更突出。

---

## 6. 第五层成功：Fc 不是装饰，它可能是药效核心放大器

IBI352g4a 最重要的贡献，是比较了不同 Fc format。

论文做了两类关键比较：

```text
mouse surrogate anti-PVRIG：
muIgG2a Fc > muIgG1 Fc

human anti-PVRIG：
huIgG1 Fc > huIgG4 Fc
```

在 humanized B-NDG hIL15 模型中，huIgG1 格式比 huIgG4 格式有更强抗肿瘤效果，也观察到更多 NK cells。

机制解释是：

```text
PVRIG blockade 解除 PVRIG-PVRL2 抑制
        +
IgG1 Fc 结合 NK cell 上 CD16a / FcγRIIIA
        ↓
PVRIG pathway 和 CD16a pathway 双重参与
        ↓
NK activation 更强
        ↓
体内抗肿瘤效果更强
```

这和 COM701/Tab5 案例形成互补：

```text
COM701/CPA.7.021/Tab5 告诉我们：阻断表位可行。
IBI352g4a 告诉我们：如果要体内强药效，Fc/NK 可能不可忽略。
```

---

## 7. 对我们后续机制建模的启发

### 7.1 不要把 binding score 当成最终药效分数

IBI352g4a 的分层证据说明：

```text
PVRIG binding Kd
PVRIG-PVRL2 blocking IC50
NK activation
T cell activation
in vivo tumor growth inhibition
```

这些不是同一个指标，不能混成一个简单 docking score。

后续建模时建议分成：

```text
1. Antigen binding score：是否结合 PVRIG ECD
2. Ligand blocking score：是否阻断 PVRIG-PVRL2
3. Epitope competition score：是否覆盖 consensus interface / R95 等 hotspot
4. Format compatibility score：VHH / VHH-Fc / IgG / bispecific 是否适合当前机制
5. Cell-context score：是否可能在 NK-rich / PVRL2-high context 中更有效
6. Developability score：表达、纯度、稳定性、聚集、PTM、Cys 风险
```

### 7.2 如果最终提交是裸 VHH，IBI352g4a 的 Fc 结论不能直接套用

这点要特别谨慎。

IBI352g4a 的 Fc/NK 机制对 IgG1、VHH-Fc、双抗、Fc-fusion 非常重要；但如果比赛提交的是裸 VHH，裸 VHH 本身没有 Fc engagement。

所以对裸 VHH 来说，它主要启发的是：

```text
1. 必须强 blocking PVRIG-PVRL2；
2. 要考虑 NK cell 上 PVRIG 的功能；
3. 后续如果要转药物 format，Fc 或多价设计可能决定体内效果；
4. 不能用体外 T cell readout 阴性就否定 PVRIG blocker。
```

### 7.3 如果未来做 VHH-Fc 或双抗，Fc/NK 应作为独立设计维度

Case 02 的 VHH-151/30 与 TIGIT-PVRIG 双抗案例已经提示 format 很重要。IBI352g4a 把这个逻辑补完整：

```text
VHH paratope 决定能不能挡住 PVRL2；
Fc / bispecific architecture 决定能不能把 NK/T cell context 放大成体内药效。
```

---

## 8. 当前缺口和不能过度解读的地方

1. 当前没有找到公开 IBI352g4a-PVRIG 复合物结构，所以不能把它直接映射到 8X6B/9E6Y 的某个残基表位。
2. 论文没有在正文中公开完整 VH/VL 序列；它不是我们当前的 official positive sequence reference。
3. Fc 结论依赖具体 format 和细胞模型，不能直接等价为“所有 anti-PVRIG 都必须用 IgG1”。
4. 体内模型是 preclinical，不等于临床已经证明。
5. 对我们当前的 VHH 第一阶段而言，IBI352g4a 主要提供机制约束，不提供可直接复制的 CDR 模板。

---

## 9. 一句话结论

> IBI352g4a 证明：一个成功的 PVRIG blocker 不只是 CDR 占住 PVRIG-PVRL2 界面；在体内药效层面，NK cell activation 和 FcγR/CD16a coengagement 可能是把 blocking 转化成强抗肿瘤效果的关键放大器。

因此它给后续模型的最大启发是：

```text
第一步仍然筛 PVRIG-PVRL2 blocking epitope；
但第二步必须把 antibody format、NK context 和 Fc engagement 从 docking/binding 中拆出来单独评价。
```

---

## 10. 主要来源

- Xue H. et al. Characterization of a novel anti-PVRIG antibody with Fc-competent function that exerts strong antitumor effects via NK activation in preclinical models. Cancer Immunology, Immunotherapy. 2024. DOI: 10.1007/s00262-024-03671-z. https://link.springer.com/article/10.1007/s00262-024-03671-z
- PubMed: https://pubmed.ncbi.nlm.nih.gov/38554184/
- PubMed Central full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC10981589/
