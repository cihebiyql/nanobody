# PVRIG-PVRL2 机制当前结论

## 1. 当前问题重新定义

现在要解决的不是“从数据库里筛出 PVRIG binder”，而是先搞清楚：

```text
PVRIG 和 PVRL2 到底怎么结合？
哪些 PVRIG 残基构成阻断功能表位？
哪些位点是结构共识支持，哪些只是专利/抗体表位线索？
后续 AI 模型应该围绕哪些机制特征打分？
```

因此当前输出是机制约束和可视化材料，不是最终抗体候选。

## 2. 结构输入

当前使用两个 PVRIG-PVRL2 复合物结构：

| PDB | PVRIG chain | PVRL2/Nectin-2 chain | 用途 |
| --- | --- | --- | --- |
| 8X6B | B | A | PVRIG 与 Nectin-2/PVRL2 复合物结构 |
| 9E6Y | A | D | CD112/Nectin-2 D1 与 CD112R/PVRIG 复合物结构 |

两个结构的 PVRIG residue numbering 不一致，所以当前所有共识界面都按 alignment column 对齐，而不是直接按 PDB residue number 合并。

## 3. 结合方式的核心理解

PVRIG-PVRL2 的结合不是深口袋式小分子结合，而是两个 Ig-like domain 的表面贴合。

从可视化上看：

- PVRL2 以灰色 beta-sandwich 表面贴到 PVRIG 的前表面；
- PVRIG 上有一片连续表面被 PVRL2 覆盖；
- 阻断抗体真正要做的是占住或干扰这片表面，让 PVRL2 不能再以正确角度贴上来；
- 所以后续模型要重视空间位阻和 interface coverage，而不是只看是否能结合 PVRIG 任意位置。

## 4. 当前 hotspot 分类

文件：`data/structures/PVRIG_hotspot_set_v1.csv`

当前分为三类：

| 类别 | 数量 | 含义 |
| --- | ---: | --- |
| core_hotspot | 21 | 8X6B 和 9E6Y 都支持的 PVRIG-PVRL2 共识界面残基 |
| secondary_hotspot | 2 | 只有一个结构在 4.5 A cutoff 下支持的边缘/动态接触残基 |
| soft_hint | 3 | 专利/表位线索残基，不能作为硬约束 |

## 5. Core hotspots

当前 21 个 core hotspots 对应的 PVRIG UniProt Q6DKI7 位置包括：

```text
S71, L72, T74, N81, G82, A83,
V90, H92, R95, G96, R98, W100,
K135, A137, S138, F139, P140, E141, G142, S143, W144
```

这些是目前最可靠的 blocking-interface seed。

其中值得优先观察的局部区域：

```text
H92 / R95 / G96 / I97 / R98 / W100
K135 / A137 / S138 / F139 / P140 / E141 / G142 / S143 / W144
```

这些区域形成了 PVRL2 贴合时的主要表面接触带。

## 6. R95 / I97 / S67 的判断

文件：`data/structures/PVRIG_key_contact_residues_v1.csv`

### R95

结论：强 soft hint。

原因：

- R95 是 patent/epitope mapping 提示位点；
- 它同时落在 8X6B 和 9E6Y 的 consensus interface；
- 它在两个结构中都直接接触 PVRL2 附近芳香族/疏水区域。

具体接触：

```text
8X6B: PVRIG B57 / UniProt R95 -> PVRL2 TYR34, PHE115
9E6Y: PVRIG A55 / UniProt R95 -> PVRL2 TYR64, PHE145
```

因此 R95 后续可以作为“高权重软提示”，但仍不是硬约束。

### I97

结论：弱 soft hint / 边缘支持。

原因：

- I97 可以映射到两个结构；
- 但当前 4.5 A distance interface 下，只有 8X6B 支持它直接接触 PVRL2；
- 9E6Y 中同一 alignment column 没有形成当前 cutoff 下的直接接触。

具体接触：

```text
8X6B: PVRIG B59 / UniProt I97 -> PVRL2 PHE115
9E6Y: PVRIG A57 / UniProt I97 -> no 4.5 A contact
```

因此 I97 可以保留为低权重 soft hint。

### S67

结论：当前不用于 Phase I 机制评分。

原因：

- S67 能映射到两个结构；
- 但它不在当前 PVRIG-PVRL2 4.5 A distance interface；
- 不能要求候选抗体必须接触 S67。

具体状态：

```text
8X6B: PVRIG B29 / UniProt S67 -> no 4.5 A contact
9E6Y: PVRIG A27 / UniProt S67 -> no 4.5 A contact
```

## 7. 最密集接触残基

从 `PVRIG_key_contact_residues_v1.csv` 看，当前接触比较密集的 PVRIG 位点包括：

| UniProt 位点 | 结构支持 | 解释 |
| --- | --- | --- |
| F139 | 8X6B / 9E6Y | 接触数量高，处在主要贴合面 |
| L72 | 8X6B / 9E6Y | 位于共识界面边缘/表面贴合区 |
| V90 | 8X6B / 9E6Y | 与 PVRL2 疏水/芳香区域相邻 |
| S143 | 8X6B / 9E6Y | 多个近距离接触，可能参与稳定贴合 |
| K135 | 8X6B / 9E6Y | 带电接触相关，值得后续看 salt bridge/氢键 |
| R95 | 8X6B / 9E6Y | 兼具 patent hint 与 consensus interface 支持 |

注意：这里仍然是 distance-only baseline，不是能量分解。

## 8. 当前机制假设

后续抗体/VHH 如果要阻断 PVRIG-PVRL2，应优先满足：

```text
1. 靶向 PVRIG 的 consensus interface 表面；
2. 覆盖 core hotspots 中的一部分连续表面；
3. 最好靠近 R95 / H92 / R98 / W100 这一带；
4. 允许接近 I97，但不能强制；
5. 不应为了 S67 牺牲对真实 PVRIG-PVRL2 interface 的覆盖；
6. 需要形成空间位阻，使 PVRL2 不能再按原来的 beta-sandwich 表面贴合。
```

## 9. 当前限制

当前分析还不是完整机制模型，因为：

- interface 定义主要来自 4.5 A heavy-atom distance；
- 尚未做 delta SASA / buried surface area；
- 尚未做氢键、盐桥、水介导接触、疏水 patch 定量；
- 尚未考虑糖基化、膜近端几何、分子动力学或构象变化；
- 尚未纳入更多结构论文和抗体阻断实验数据。

## 10. 下一步建议

下一步机制挖掘应优先做：

```text
1. 系统查 PVRIG-PVRL2 / CD112R-Nectin-2 结构论文；
2. 提取论文中提到的 CC' loop、F-strand charged residues、double-lock-and-key 等具体残基；
3. 对 8X6B / 9E6Y 做 delta SASA、氢键、盐桥、疏水接触表；
4. 查 COM701、Tab5、HR-151、PVRIG patents 中是否有 epitope/binning/blocking data；
5. 把结构接触、文献突变、抗体表位映射合成一个 mechanism evidence matrix。
```

## 11. 真实案例补充洞察

逐例案例拆解已经补充到 `case_studies/`：

```text
Case 01：COM701 / CPA.7.021 / Tab5
Case 02：PVRIG-20/30/38/39/151 / HR-151 VHH
Case 03：IBI352g4a / Fc-competent IgG1 / NK activation
Case 04：GSK4381562 / SRF813 / remzistotug / distinct epitope
```

这些案例给当前机制模型增加了三条约束：

- **binder != blocker**：COM701/Tab5 类案例说明，普通 PVRIG binding 不是目标，必须能阻断 PVRIG-PVRL2。
- **VHH 也能 block 表面界面**：PVRIG-20/30/38/39/151 说明，长 CDR3 和 VHH format 可以有效覆盖或干扰 Ig-like domain 表面贴合。
- **blocking 不等于体内药效**：IBI352g4a 说明，Fc format、NK cell activation、CD16a/FcγR coengagement 会影响 PVRIG blocker 在体内能否转化为强抗肿瘤效果。
- **不能过拟合单一表位**：GSK4381562/SRF813/remzistotug 的 distinct epitope 主张说明，PVRIG blocker 可以有不同表位 solution；模型要允许 alternative blocking angle，但仍必须保留 PVRIG-PVRL2/CD112 blocking 约束。

因此后续模型至少要拆成两层：

```text
分子层：PVRIG binding + PVRIG-PVRL2 blocking + epitope/interface coverage
细胞层：format compatibility + NK/T cell context + FcγR engagement
校对层：positive leakage exclusion + distinct-epitope allowance + non-blocking binder rejection
```
