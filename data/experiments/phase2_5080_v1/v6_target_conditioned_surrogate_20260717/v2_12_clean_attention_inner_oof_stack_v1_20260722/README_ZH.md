# V2.12 Clean-Attention whole-parent OOF 与后续融合

## 目的

本版本为 `B_CLEAN_TARGET_ATTENTION` 生成严格的五折训练集 OOF 预测，供后续与已有 `S0/M2/C2` OOF 证据进行泄漏安全的二级融合。

```text
canonical10644 的原训练区：9,849 条 / 54 parent clusters
→ GroupKFold(5)，每个 parent 只进入一个 score fold
→ 每 fold 从同一冻结 ESM2-650M 重新训练，固定 seed=43
→ 汇总每条候选恰好一次的 Clean-Attention OOF 预测
```

原开放开发集 `795 条 / 10 parents` 和 frozen test 不参与本阶段的训练、前向、选择或评价。

## 模型输入与边界

神经分支只允许：

- 冻结 ESM2-650M residue token；
- label-free VHH 单体 residue graph；
- 固定公开的 8X6B/9E6Y PVRIG target graphs。

禁止输入 M2/C2、接触标签、候选/parent ID、campaign、Docking pose 或 pose-derived 特征。模型直接预测 `R_8X6B` 和 `R_9E6Y`，`R_dual_min` 在推理时严格取两者的最小值。

本结果只支持 **whole-parent OOF**。审计发现 exact CDR3 会跨 parent 重复，因此不能把它表述为 CDR3-family 或 sequence-family OOD。

## 冻结折分

| fold | train rows | score rows | train parents | score parents |
|---:|---:|---:|---:|---:|
| 0 | 7,870 | 1,979 | 44 | 10 |
| 1 | 7,869 | 1,980 | 44 | 10 |
| 2 | 7,880 | 1,969 | 44 | 10 |
| 3 | 7,848 | 2,001 | 44 | 10 |
| 4 | 7,929 | 1,920 | 40 | 14 |

五折 score candidate 的交集为空，union 精确覆盖 9,849 条。

## 固定训练设置

- seed：43（所有 fold 相同，避免 seed 与 fold 混杂）
- epochs：8，固定轮数，无 early stopping
- batch size：8
- gradient accumulation：4
- precision：BF16
- optimizer：AdamW，LR `1e-4`，weight decay `0.02`
- dropout：`0.25`
- 4 GPU 两波执行：第一波 F0–F3，全部通过后第二波 F4

## 终态门控

聚合只有在以下条件全部满足时发布：

- 5/5 fold receipt 均为 PASS；
- train/score parent overlap 为 0；
- 9,849 个 candidate 无遗漏、无重复且 identity/hash 闭合；
- truth/prediction 的 exact-min 数值闭合；
- open-development 与 frozen-test access 均为 0；
- 所有输入输出 SHA256 闭合。

成功终态：

```text
PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_AND_AGGREGATE
```

## 下一阶段

V2.12 OOF 完成后，合并已有 9,849 行 `S0/M2/C2` OOF，先训练强正则、低维的线性 stack，再用 parent-level meta cross-fitting 诚实评估早期富集。不能在同一批 OOF 行上训练 meta-head 后把训练内性能称为 OOF 性能。

