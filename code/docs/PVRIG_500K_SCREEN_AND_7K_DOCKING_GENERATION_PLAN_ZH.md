# PVRIG 50万序列筛选与新增约7000条Docking教师生成方案

更新时间：2026-07-19

## 1. 当前真实起点

- 已物化的标量教师表为 3,388 条独立 VHH、6,776 个受体特异标量目标、31 个 parent clusters。
- 组成：V4-D 226 + V4-H 1,281 + V4-I 1,881。
- 多 seed 1,066，单 seed 2,322。
- V4-I 新增的 1,881 条来自既有 11 个 parent，新增 parent=0。
- 完整 3,388 条的正式 OOF 重训练尚未完成；当前最强已验证模型仍是 open1507 的 M2 exact-min whole-parent OOF，Rdual Spearman 约 0.61。
- sequence-only open-inner Ridge ESM2-650M 约 0.43，只能用于早期富集与主动学习，不能承担最终精确排序。

因此后续工作顺序应是：

```text
先完成 D0=1507 / D1=2007 / D2=3388 同口径 whole-parent OOF
→ 冻结可用于 acquisition 的模型与不确定性
→ 生成候选前池
→ 选择约7000条新增双受体Docking
→ 总有效教师达到约10000
→ 训练下一版模型
→ 100k pilot
→ 500k生产池
```

## 2. 对现有建议的判断

总体合理，必须保留：

1. 新 parent 优先于更多 sibling；
2. 高/中/低/不确定样本同时进入 Docking；
3. exact-min、双受体、失败为 NA；
4. whole-parent + CDR3 family split；
5. generator/campaign/parent 仅作审计与采样，不作模型特征；
6. 多 seed sentinel 必须无偏覆盖全分布。

需要修正：

1. 当前是 3,388 条“可训练教师表已物化”，不是 3,388 条新模型已经训练完成。
2. 如果目标是总量约 10k，不需要再新增 10k；应提交约 7,000 条以抵消技术失败，预计得到约 6.7k 有效 paired labels。
3. AntiFold、本地 latent/de novo、独立 fixed-pose optimizer 当前不是完整生产链，不能让它们承担关键产量。
4. 生成方法比例与高/中/低 acquisition 比例是两个正交维度，必须分别配额，不能混成一个表。

## 3. 新增7000条的parent配置

建议先使用 80 个 parent clusters：

```text
60 个新 parent × 80 条 = 4,800
20 个既有 parent × 80 条 = 1,600
实验性/跨parent/机制对照       =   600
总计                          = 7,000
```

- 60 个新 parent 从 `scaffolds/top_200_vhh_scaffolds_for_design.csv` 中选取；该表有 200 条、200 个独立 cluster。
- 新 parent 占新增库约 69%。
- 既有 parent 用于 exploitation 和与旧数据连接。
- 同一 parent 的近邻、同 backbone siblings、mutation ladder 必须进入同一个 split。
- 任何 parent 在新增7000中不超过 2%；设计目标约 80 条/parent。

## 4. 生成方法配置

### 4.1 主生产配额

| 生成路线 | 数量 | 状态 |
|---|---:|---|
| 天然 scaffold 上保守 CDR redesign | 2,800 | 可由天然 parent + RFantibody/ProteinMPNN 实现 |
| RFantibody target-conditioned 新 backbone | 1,750 | Node1 已有脚本、权重和千级运行证据 |
| ProteinMPNN 固定 backbone 局部扩增 | 1,750 | 已运行；temperature 做 0.1/0.2/0.3 对照 |
| matched mutation ladder/破坏性对照 | 350 | 需版本化生成器，保留局部排序监督 |
| AntiFold/latent/de novo 实验 lane | 350 | 仅在 smoke 与权重闭合后纳入；失败则回拨给 matched ProteinMPNN |

独立 fixed-pose optimizer 当前未找到生产脚本，不单独承诺产量。ProteinMPNN 只能优化给定 backbone 的序列，不会重新优化整体 docking pose。

### 4.2 RFantibody参数轴

- target patch：A/B/C 大致均衡，同时保留 P2/P3/P4 exploitation 和 P1/P5/P6/holdout 对照；
- design mode：H3 40%，H1+H3 35%，H1/H2/H3 20%，探索模式5%；
- H3 length：11/13/14/15 为主，5-10 与16-20作分层探索；
- RFdiffusion：优先增加不同 backbone，不只在 winner backbone 上大量采 sibling；
- ProteinMPNN temperature：0.1/0.2/0.3；
- 每 backbone 推荐 4-12 条进入候选前池，最终进入7000的同backbone sibling更少；
- seed、backbone index、MPNN index、版本和权重hash全部写入manifest。

## 5. 7000条不是直接生成，而是从前池分层抽取

建议先生成约 60k-100k raw discovery candidates：

```text
60k-100k raw
→ exact dedup / ANARCI / CDR / novelty / hard QC
→ 约30k-50k sequence-QC pass
→ sequence ensemble + binding-prior + uncertainty
→ 约20k预测单体结构或复用生成backbone
→ M2结构分 + sequence分 + disagreement
→ 分层冻结7000条Docking manifest
```

7000条 acquisition bucket：

| bucket | 数量 | 选取方式 |
|---|---:|---|
| predicted high exploitation | 2,450 | 每parent/patch/method内取高分，不做全局纯Top |
| medium/boundary | 1,400 | 中位分数、阈值附近 |
| low but QC-pass | 1,050 | 分层随机低分对照 |
| uncertainty/model disagreement | 1,050 | sequence/M2/binding models分歧、高不确定 |
| acquisition-independent new-parent sentinel | 1,050 | 不依赖当前模型Top分，从新parent/patch网格预先抽取 |

各 bucket 再按 parent、patch、mode、generator 配平；同一候选只能进入一个 bucket。

## 6. 新增7000条的Docking任务量

```text
全部7000：双受体 × seed917          = 14,000 jobs
分层1400：再补seed1931 × 双受体     =  2,800 jobs
其中350：再补seed3253 × 双受体      =    700 jobs
总计                               = 17,500 jobs
```

1400/350 repeat-seed必须覆盖高、中、低、新parent、不同generator和不确定样本，不能只重复Top候选。

## 7. 50万条序列如何生成

先做 100k pilot，再扩展余下400k。

建议500k方法配额：

| 路线 | 数量 |
|---|---:|
| 天然200 scaffold保守CDR redesign | 200k |
| RFantibody target-conditioned backbone | 125k |
| ProteinMPNN fixed-backbone expansion | 100k |
| fixed-backbone/mutation optimization | 50k |
| AntiFold/latent/de novo探索 | 25k |

实验路线只有在100k pilot证明unique yield、QC pass和预测分布有效后才扩量。

## 8. 50万筛选漏斗

### Stage 0：身份与硬门

- 标准20 aa、长度95-160；
- exact sequence dedup；
- ANARCI/IMGT成功，FR/CDR完整；
- 保守Cys/framework；
- 无stop、非法字符、严重低复杂度、疏水长串；
- known-positive任一CDR identity <80%，正式提交优先<75%。

目标：500k → 350k-420k。

### Stage 1：快速可开发性与合成风险

- hydrophobic run、free cysteine、N-glyc、deamidation、isomerization；
- charge/pI、aggregation/polyreactivity proxy；
- `developability_score`；
- `expression_purity_risk_score`。

此阶段不全量运行TNP。目标：350k-420k → 180k-250k。

### Stage 2：sequence-only多模型

- V2.8 sequence ensemble（仅在D0/D1/D2 OOF通过后）；
- DeepNano、NABP-BERT、NanoBind等作为独立binding prior列；
- model disagreement、OOD、near-CDR3 family、parent配额。

这些binding模型不是Kd预测器，不作单一hard gate。目标：180k-250k → 60k-100k。

### Stage 3：完整QC

- official validator；
- AbNatiV、Sapiens；
- 对较小shortlist补TNP；
- expression/purity风险分继续单独保存。

目标：60k-100k → 30k-50k。

### Stage 4：结构层

- 选20k-30k预测或复用VHH单体结构；
- 结构QC；
- 126D M2、coarse-pose、marginal-contact和模型分歧。

目标：20k-30k → 10k-15k。

### Stage 5：选择5000条实际Docking

```text
55%  high exploitation           2750
20%  uncertainty/disagreement    1000
15%  new-parent/diversity/OOD      750
10%  calibration/low sentinel      500
```

不能纯取Top5000。

## 9. 亲和力、纯度和阻断分开保存

- Docking surrogate：阻断样几何排序；
- DeepNano/NABP/NanoBind：generic binding/relative affinity prior；
- `expression_purity_risk_score`、AbNatiV、Sapiens、TNP：可开发性/表达/纯度风险代理；
- 没有PVRIG-specific BLI/SPR时不输出可信Kd；
- 不建议在早期把全部列强行压成一个总分，先用hard gates + Pareto fronts + portfolio quotas。

## 10. 立即执行顺序

1. 完成D0/D1/D2 whole-parent OOF，确认3388是否真正改善early enrichment；
2. 为200个top scaffolds建立parent结构/编号/可生成性manifest；
3. 先跑8-12个新parent、每parent一个小arm的generation smoke；
4. 冻结7000 campaign的parent/patch/mode/method/acquisition配额；
5. 生成60k-100k discovery pool并运行漏斗；
6. 冻结7000 candidate manifest和无偏repeat-seed sentinel；
7. 执行17,500个candidate docking jobs；
8. 形成总量约10k的版本化teacher并训练下一版模型；
9. 先筛100k pilot，达到门槛后扩展到500k。

