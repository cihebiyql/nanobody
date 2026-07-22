# V2.16 RAW HARD-NEGATIVE TOP5

V2.15 证明原始 162D 单体/粗姿势特征与 L1 的 Top5 列表互补，但在全体样本上训练分类器不能识别多模型并集中的真阳性。V2.16 将训练域限制为 S0/M2/C2/L1 的 top20%/top30% 候选并集，只学习困难候选间的区别。

所有预测仍是 9,849 行、54 parent、固定五折 whole-parent OOF；open development 与 frozen test 均不访问。主指标为 Docking top10% 在预算 5% 下的 EF。
