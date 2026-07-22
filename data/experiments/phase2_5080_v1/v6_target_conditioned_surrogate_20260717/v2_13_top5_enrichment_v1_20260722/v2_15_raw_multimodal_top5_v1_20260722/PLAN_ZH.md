# V2.15 RAW-MULTIMODAL-TOP5

## 目标

在不读取 open development 和 frozen test 的前提下，用 9,849 条 whole-parent OOF teacher 检验：原始 126D VHH 单体结构特征、36D 廉价双受体粗姿势特征，以及 S0/M2/C2/L1 的 OOF 预测，能否识别多模型候选并集中的真正 Docking Top 10%，从而提高 EF@5%。

## 数据与边界

- 训练/评价：9,849 条，54 个 parent cluster，固定 5 个 whole-parent folds。
- 监督：`R8`、`R9`，推理时 `Rdual=min(R8,R9)`。
- raw multimodal 总表含 795 条 open-development 行；读取时先用 assignment 中的 candidate id 做行级防火墙，未匹配行不解析任何特征或标签。
- 禁止输入 candidate id、parent id、campaign id、teacher source、任何 Docking pose-derived teacher 字段。
- 允许的 coarse-pose 特征是对两个固定靶标做的 label-free 廉价刚体扫描结果，不是 HADDOCK teacher。

## 冻结候选

- `G0_EQUAL_RANK4`：S0/M2/C2/L1 等权 percentile-rank 基线。
- `G1_HGB_TOP10_RAW`：浅层 HistGradientBoosting Top10 分类。
- `G2_EXTRA_TREES_TOP10_RAW`：强正则 ExtraTrees Top10 分类。
- `G3_HGB_R8R9_RAW`：分别回归 R8/R9，再取 exact min。
- `G4_CLASSIFIER_MEAN`：G1/G2 OOF percentile-rank 均值。
- `G5_CLASSIFIER_BASE_BLEND`：70% G4 + 30% G0。

所有模型严格按 outer fold 训练，任何一行预测都来自未见过该 parent cluster 的模型。

## 成功标准

主指标为 pooled EF(true Docking top10%, budget5%)。若任一 challenger 达到 EF5=5，则记录目标达成；否则仅作为下一轮信息，不访问 frozen test。
