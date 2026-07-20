# PVRIG VHH 纯度、表达与可开发性计算流程审计

更新日期：2026-07-19

## 1. 结论先行

当前流程**可以用于计算端的高风险排雷和候选优先级排序**，但还不能称为可靠的“纯度预测模型”或“表达量预测模型”。

原因是：

1. 当前的 `developability_score` 和 `expression_purity_risk_score` 是人工规则组合分，不是用实测表达量、纯度或 SEC 数据训练得到的模型。
2. 当前 24 条前瞻候选的实验结果表全部处于 `PENDING`，可用于校准的实测样本数为 0。
3. 现有一次正式 24 条计算级联在 full-QC 阶段使用了 `--skip-tnp`；另一个 100 条深度 QC 批次中 AbNatiV 和 Sapiens 覆盖率均为 0/100，工具覆盖尚不统一。
4. 当前初筛组合公式将同一个 `expression_score` 同时用于“表达 20%”和“纯度 10%”，实际上是同一代理分占 30%，并没有独立的表达与纯度模型。

因此，现阶段最正确的名称是：

> **表达/纯度风险代理分（expression/purity risk proxy）**

而不是：

> 预测纯度、预测表达量、通过率概率或比赛得分。

## 2. 当前流程是什么

Node1 主要实现位于：

```text
/data1/qlyu/software/vhh_eval_tools/vhh_screen.py
/data1/qlyu/software/vhh_eval_tools/competition_qc/vhh_competition_qc.py
```

流程可分为三层。

### 2.1 L1：序列合法性和编号

- 标准氨基酸字符检查；
- ANARCI/IMGT/Kabat 编号；
- FR/CDR 完整性；
- VHH framework 基本保守位点检查。

这一层适合做 hard gate。它判断的是序列是否像一个可继续处理的 VHH，而不是纯度。

### 2.2 L2：VHH 天然性与框架合理性

主要包括：

- FR2 hallmark；
- H44/H45/H47 等 VHH 界面特征；
- AbNatiV VHH score；
- single-domain suitability。

当前 AbNatiV 规则大致为：

```text
<0.55       FAIL
0.55–0.70   WARN
>=0.70      较可接受
```

AbNatiV 是真实模型输出，但它预测的是序列相对于天然 VHH 分布的“天然性”，不是表达量或纯度。天然性较差往往提示风险，但二者不是一一对应关系。

### 2.3 L3：可开发性风险

输入包括：

- 理论 pI；
- pH 7.4 净电荷；
- GRAVY；
- instability index；
- Cys 数量；
- N-糖基化、脱酰胺、异构化、DP 裂解等序列 motif；
- 连续疏水片段；
- polybasic、polyacidic、RGD 等规则；
- polyreactivity proxy；
- TNP 的 PSH、PPC、PNC 等结构风险标志。

这层回答的是：该序列是否具有聚集、非特异性、异常电荷、化学不稳定或生产困难的风险。它并不直接计算纯化后样品的 HPLC 纯度、SEC 单体比例或表达产量。

## 3. 每个工具实际代表什么

| 工具/输出 | 实际含义 | 与纯度的关系 | 当前建议 |
|---|---|---|---|
| ANARCI/官方 validator | VHH 编号、结构域完整性 | 间接 | 可作 hard gate |
| ProtParam | pI、GRAVY、instability、MW 等确定性描述符 | 间接风险 | 快速软筛 |
| motif/liability 规则 | 糖基化、脱酰胺、疏水串、异常 Cys 等 | 间接风险 | 严重项 hard gate，其余软惩罚 |
| AbNatiV | VHH 天然性/分布内程度 | 间接相关 | 独立列和排序特征，不当作纯度 |
| Sapiens | 人源化/人样性建议 | 与纯度关系很弱 | 仅用于人源化审计，不作为纯度分 |
| TNP | 结构层面的 PSH/PPC/PNC 等风险 | 可能提示聚集或多反应性 | 短名单补充，不当作实测纯度 |
| `developability_score` | 人工加减分汇总 | 未校准 | 风险排序 |
| `expression_purity_risk_score` | pI、电荷、疏水性、稳定性、Cys、TNP 等人工组合 | 未校准 | 风险排序，不能解释成概率 |

## 4. 两个复合分怎样计算

### 4.1 `developability_score`

从 100 分开始，按规则扣分，例如：

- L3 WARN：约减 12；
- L3 FAIL：约减 45；
- N-糖基化、脱酰胺、异构化、DP 裂解 motif：分别扣分；
- Cys 数量不是 2：扣分；
- AbNatiV 较低：扣分；
- TNP 风险标志：扣分。

这是可解释的经验规则，但权重不是由表达/纯度实验数据拟合得到的。

### 4.2 `expression_purity_risk_score`

同样从 100 分开始，主要按以下风险扣分：

- 极端 pI 或高净电荷；
- GRAVY 偏高；
- instability index 偏高；
- 五残基连续疏水串；
- Cys 数量异常；
- polyreactivity proxy；
- TNP 的 PSH/PPC/PNC 标志。

需要特别注意：部分字段缺失时，代码会用相对温和的默认值，例如 pI=7、charge=0、GRAVY=-0.2、instability=30。这会使缺失数据的候选得到偏乐观的分数。因此必须同时保存 `tool_coverage` 和 `missingness`，禁止只看最后的 0–100 分。

## 5. 当前运行证据

### 5.1 24 条正式候选

正式 cascade 最终有 4 条进入 full-QC，AbNatiV 和两个复合分均有输出。但执行命令显式包含：

```text
--skip-tnp
```

因此该批次的 `TNP_flags` 不能视为真实 TNP 证据。

实验结果表：

```text
/mnt/d/work/抗体/data/experiments/phase2_5080_v1/assays/
  pvrig_v2_5_prospective_v1/expression_qc_results.csv
```

目前 24/24 都是 `PENDING`，表达量、纯度、SEC 单体比例和聚集比例均为空。

### 5.2 100 条深度 QC

当前汇总覆盖：

```text
pI/GRAVY/charge     100/100
TNP 有效结果          85/100
AbNatiV                0/100
Sapiens                0/100
```

所以它也不是全工具覆盖的统一纯度评估批次。

### 5.3 已知阳性 VHH

已知结合阳性在当前复合分中的波动较大，例如表达/纯度风险分约 45–100、可开发性分约 32–80。这只能说明规则会区分风险，不能验证纯度预测能力，因为这些阳性并没有配套的实测表达量和纯度标签。

## 6. 可靠性分级

| 层级 | 当前可靠性 | 可作何用 |
|---|---|---|
| 序列合法性、编号、确定性描述符 | 高可复现 | hard gate/审计 |
| 明显异常 Cys、极端疏水串等风险规则 | 中高 | 高风险排雷 |
| AbNatiV 天然性 | 对其自身任务可靠 | 软排序，不等于纯度 |
| TNP 结构风险 | 中等、依赖结构模型 | 短名单复核 |
| `developability_score` | 中低 | 经验风险排序 |
| `expression_purity_risk_score` | 低至中低 | 未校准的风险代理 |
| 定量预测纯度/表达量 | 当前不可靠 | 不能直接使用 |

## 7. 现阶段怎样加入大规模筛选

对 50 万条序列，建议分层运行：

```text
第一层：字符、长度、编号、FR/CDR、明显异常 Cys、严重疏水串
第二层：pI、charge、GRAVY、instability、motif/liability
第三层：AbNatiV，保留原始分数
第四层：对短名单运行 TNP
第五层：与 binding prior、双构象 docking 分开做多目标排序
```

原则：

1. 只对明确无效或极端高风险项使用 hard fail；
2. AbNatiV、TNP、pI 等大多数指标使用 soft penalty；
3. 每一项保留原始列，不能只保留总分；
4. 工具缺失记为 `NA`，不能用正常默认值冒充通过；
5. Sapiens 不进入纯度分，只用于人源化路线；
6. Docking、binding prior、表达/纯度风险必须保持不同证据通道。

## 8. 怎样才能验证为可靠模型

需要先冻结实验终点，例如：

- `expression_yield_mg_per_l`；
- `purity_fraction`；
- `sec_monomer_fraction`；
- `aggregation_fraction`。

然后按 parent、CDR3 cluster 和生成批次分组划分训练/验证/测试集，禁止把高度相似 sibling 随机分到两侧。

建议分别评价：

- 表达量：Spearman、log-yield MAE；
- 纯度：MAE/RMSE、Spearman；
- 合格/不合格：AUPR、AUROC、校准误差和假阴性率；
- SEC 单体和聚集：独立建模，不能混成一个标签。

做增量消融：

```text
ProtParam + liabilities
  -> + AbNatiV
  -> + TNP
  -> + Sapiens
```

只有当独立测试集上新增特征稳定提高指标，才能证明它对本项目的表达或纯度有增益。

## 9. 对比赛评分的直接建议

当前不能直接实现：

```text
初筛 = 结合 70% + 表达 20% + 纯度 10%
```

因为表达和纯度尚无独立、校准过的预测器。过渡阶段可改为：

```text
结合/阻断几何：独立排序通道
表达风险代理：独立通道
纯度/聚集风险代理：独立通道
多样性与新颖性：约束通道
```

先做 Pareto 排序或分层筛选，不宜用未经校准的固定百分比加权。等获得实测标签后，再拟合表达模型和纯度模型，并用冻结测试集确定权重。

## 10. 最终判断

当前流程不是无效：它对淘汰明显异常、极端疏水、异常电荷、非天然框架和结构风险候选很有价值，并且运行成本低于结构预测和 docking。

但它目前的可靠边界是：

> **可开发性风险筛查与排序，而非定量纯度/表达预测。**

在没有实验标签时，应把它作为前筛和多目标优化的一条独立证据链，不应把 0–100 复合分当作实测纯度、表达量或比赛通过概率。
