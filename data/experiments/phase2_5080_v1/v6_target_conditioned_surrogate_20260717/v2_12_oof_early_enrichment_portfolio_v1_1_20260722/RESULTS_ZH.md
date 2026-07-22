# V2.12 Clean-Attention OOF 与四模态 portfolio 结果

## 1. Clean-Attention whole-parent OOF

五折训练和聚合全部通过：

```text
9,849 rows
54 parent clusters
5 folds
seed 43
candidate duplicate/missing = 0
open-development access = 0
frozen-test access = 0
```

OOF 指标：

| 指标 | 结果 |
|---|---:|
| Rdual Spearman | 0.5674 |
| Rdual MAE | 0.03542 |
| EF@5%，true top-10% | 2.2107 |
| Recall@5%，true top-10% | 11.07% |
| within-parent top20 macro recall | 31.68% |

这说明 Clean-Attention 在真正未见 parent 上保留了中等排序信号，但不同 fold 差异较大，不能单独替代其他模态。

## 2. 四模态 open-development portfolio

使用 9,849 行 OOF 拟合，795 行开放开发集只用于冻结后的描述性评价。融合输入为：

- S0：序列 ESM2 基线；
- M2：VHH 单体结构特征；
- C2：廉价粗姿态扫描；
- B：Clean target-attention。

### 主要结果

| 模型 | EF@5% | 40 条中命中 | Recall@5% | EF@10% | Rdual Spearman | Rdual MAE | within-parent top20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 | 2.981 | 12 | 15.00% | 2.484 | 0.6148 | 0.03432 | 0.3796 |
| M2 | 3.230 | 13 | 16.25% | 2.981 | **0.6597** | 0.03315 | 0.3204 |
| C2 | 2.981 | 12 | 15.00% | 1.863 | 0.6085 | 0.03787 | 0.3551 |
| B | 3.230 | 13 | 16.25% | 2.733 | 0.6495 | 0.03538 | 0.3478 |
| Positive Ridge4 | 3.727 | 15 | 18.75% | 2.981 | 0.6558 | 0.03287 | 0.3889 |
| Rank percentile mean4 | **3.975** | **16** | **20.00%** | 2.857 | 0.6570 | — | 0.3770 |
| Convex4 | **3.975** | **16** | **20.00%** | **3.105** | 0.6565 | **0.03240** | **0.4032** |
| HGB top10 challenger | 3.230 | 13 | 16.25% | 2.733 | 0.6310 | — | 0.2809 |

### 结论

1. **多模态融合提高了最重要的早期富集。** 在 5% 预算、40 条候选时，单模型最多命中 13 条，Convex4/mean-rank 命中 16 条，EF 从 3.23 提升到 3.98。
2. **简单、强约束融合优于浅层分类头。** HGB 分类头没有带来增益，说明当前 54 个 parent 对非线性 meta-head 仍偏少。
3. **B 提供互补信息但不应单独主导。** B 的 open-development EF@5 与 M2 相同，但 OOF 仅为 2.21；合理做法是保留它作为约四分之一的独立证据。
4. **当前最实用前筛输出是双轨制：** `Convex4 Rdual` 用于连续几何估计，`mean percentile rank4` 用于稳健候选排序。

## 3. 证据边界

这些结果属于已经开放的 development cohort，不能提升为正式 untouched test。OOF 只保证 whole-parent 隔离，不能声称 CDR3/sequence-family OOD。模型仍然只逼近独立双受体 Docking 几何，不表示实验结合、Kd 或实验阻断概率。

## 4. 下一步

1. 将 Convex4 和 mean-rank4 固定为 V2.12 大库前筛的两个主分数；
2. 在 10 万条库上先运行廉价 S0，再对约 1–2 万条补 M2/B/C2；
3. 采用 `80% 高融合分 + 10% 高不确定性 + 10% 多样性探索` 进入 Docking；
4. 新增 Docking 数据后继续生成 whole-parent OOF，而不是直接在旧开发集上调融合权重；
5. 积累更多独立 parent 后，再重新挑战非线性分类/排序头。

