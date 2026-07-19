# PVRIG V2.6 开放 inner split 多模型早期富集审计 V1

## 结论

当前最合理的 structure-aware 召回核心不是单一模型，而是：

```text
M2（126D 单体结构/QC Ridge）
        +
F0（三 seed、target-conditioned residue/contact 模型）
        ↓
共识排序 + OR 召回 + 分歧/多样性配额
```

在当前唯一严格同分割可比的开放开发集 `outer0/inner0`（184 条、6 个未见
parent）上：

- M2、B、F0 对真值 Top10% 都有明显的早期富集；
- M2 与 F0 存在少量可用互补性；
- B 与 F0 高度重合，现阶段不值得独占一个固定召回配额；
- `M2 + F0 best-rank OR` 在固定 Top10% 预算下比任一单模型多找回 1 个
  true-Top10% 候选；
- `M2 + F0 rank-mean` 的全局 Top-K 没有明显超过 M2，但 within-parent Top20
  召回从 M2 的 37.5% 提高到 49.3%，提示它可能更适合同 parent 的 sibling
  重排。

这仍是 **开放开发证据**，不能外推成 10 万库的真实命中率，也不能称为结合、
Kd、实验阻断或 Docking Gold。

## 严格证据边界

本审计只读取：

1. 开放 `open1507` 监督表；
2. 已冻结的 whole-parent `outer0/inner0` manifest；
3. Node1 已完成的 B seed43 与 F0 seeds 43/97/193 的 184-row score predictions；
4. 开放 inner pilot collector 结果。

访问计数：

```text
V4-F/test32                 0
outer test truth            0
outer metrics               0
```

禁止把本报告用于 formal test 解封或模型晋级。`METRICS.json` 中保存了同样的
access audit。

## 同一 184-row split 上如何构建 M2

M2 不是从另一个 outer OOF 表中直接拿来混比，而是在与 B/F0 完全相同的
`outer0/inner0` 上重新拟合：

```text
1085 train rows / 22 parent clusters
184 score rows / 6 parent clusters
train-score parent overlap = 0
```

冻结构建方式：

- 输入：监督表中字段名含 `__` 的全部 126 个 label-free 单体结构/QC 特征；
- 目标：直接预测 `R_8X6B` 与 `R_9E6Y`；
- 模型：加权 Ridge，`alpha=10`；
- 权重：每个 teacher source 总权重 0.5，source 内等 parent，parent 内等候选；
- 推理：`Rdual = min(pred_R8, pred_R9)`；
- 没有 candidate ID、parent ID、campaign ID 或 Docking pose-derived 输入。

输入哈希与每个 Node1 prediction 文件哈希在 `METRICS.json` 和
`INPUT_SHA256SUMS` 中。分析脚本还精确复现了 frozen collector 的 B/F0 Rdual
Spearman、MAE 和 RMSE（容差 `1e-12`）。

## 单模型整体结果

| 模型 | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2 | 0.3066 | 0.03159 | 0.04149 |
| B seed43 | 0.2630 | 0.02975 | 0.03711 |
| F0 3-seed ensemble | 0.3173 | 0.03145 | 0.03784 |

F0 的整体相关性最高，但差距小；M2 的早期 Top-K 反而略稳。不能仅按 Spearman
选择用于召回的模型。

## 早期富集

本报告的主表对正样本数和预算数均使用：

```text
k = ceil(N × fraction)
```

因此 184 行中：

- true Top10% = 19 条；
- true Top20% = 37 条；
- predicted Top5% = 10 条；
- predicted Top10% = 19 条；
- predicted Top20% = 37 条。

### 找回 true Top10%

| 模型/融合 | Pred Top5% hits / recall / EF | Pred Top10% | Pred Top20% |
|---|---:|---:|---:|
| M2 | 7 / 36.8% / 6.78× | 12 / 63.2% / 6.12× | 15 / 78.9% / 3.93× |
| B seed43 | 7 / 36.8% / 6.78× | 11 / 57.9% / 5.61× | 14 / 73.7% / 3.66× |
| F0 ensemble | 7 / 36.8% / 6.78× | 12 / 63.2% / 6.12× | 14 / 73.7% / 3.66× |
| M2+F0 rank-mean | 7 / 36.8% / 6.78× | 12 / 63.2% / 6.12× | 15 / 78.9% / 3.93× |
| M2+F0 best-rank OR | 7 / 36.8% / 6.78× | **13 / 68.4% / 6.63×** | 14 / 73.7% / 3.66× |

### 找回 true Top20%

| 模型/融合 | Pred Top5% hits / recall / EF | Pred Top10% | Pred Top20% |
|---|---:|---:|---:|
| M2 | 9 / 24.3% / 4.48× | 15 / 40.5% / 3.93× | 19 / 51.4% / 2.55× |
| B seed43 | 8 / 21.6% / 3.98× | 14 / 37.8% / 3.66× | 17 / 45.9% / 2.28× |
| F0 ensemble | 8 / 21.6% / 3.98× | 15 / 40.5% / 3.93× | 17 / 45.9% / 2.28× |
| M2+F0 rank-mean | 8 / 21.6% / 3.98× | 15 / 40.5% / 3.93× | 19 / 51.4% / 2.55× |

## `best-rank OR` 的定义

对每个模型先计算 0–1 的 descending percentile rank（1 为最好），然后：

```text
OR_score(candidate) = max(M2_percentile, F0_percentile)
```

按 `OR_score` 取固定 K 条，而不是把两个 Top-K 无限制合并。因此它与 raw union
不同，仍保持相同 Docking 预算。

固定 Top10% 预算下，M2 与 F0 各自为 12/19，best-rank OR 为 13/19。这个增量
只有 1 条，必须在更多 whole-parent folds 上复现，不能据此冻结生产权重。

## Top-K 重合与 raw union

| 模型对 | Top5% overlap | Top10% overlap | Top20% overlap |
|---|---:|---:|---:|
| M2 vs F0 | 8/10 | 17/19 | 30/37 |
| M2 vs B | 7/10 | 18/19 | 29/37 |
| B vs F0 | 8/10 | 18/19 | 36/37 |

预测分数 Spearman：

```text
M2 vs B   0.7910
M2 vs F0  0.8451
B vs F0   0.9246
```

所以三者不是三个独立召回器。尤其 B 与 F0 几乎是同一搜索方向。

M2+F0 的 raw Top10% union 为 21 条，找回 13/19；加入 B 后仍是 21 条、13/19，
没有新增。只有 raw Top5% union 中，B 额外带来 1 个候选且该候选恰为真 Top10%，
但这是单 split、单 seed 的事后观察，不足以预留生产 quota。

## Tie-aware 审计及“6 vs 7”差异

分数分辨率：

| 模型 | unique scores / 184 | 最大 tie |
|---|---:|---:|
| M2 | 184 | 1 |
| B seed43 | 23 | 36 |
| F0 ensemble | 67 | 9 |

B/F0 的 BF16 输出存在明显 ties，因此报告同时保存每个 cutoff 的：

```text
cutoff tie size
strictly-above count
tie 中 positive 数
worst / expected random tie-break / best hits、recall、EF
```

关键边界：

- F0 trueTop10@predTop5：cutoff tie=2，两个位置都被纳入，因此当前 `ceil/ceil`
  定义下 best=expected=worst=7/10；
- F0 trueTop10@predTop10：cutoff tie=2，两个位置都被纳入，仍为稳定的 12/19；
- B trueTop10@predTop10：cutoff tie=4、只取 1 个，结果范围为 11–12 hits，随机
  tie-break 期望 11.5。

此前记录的 F0 Top5% 为 6，与本报告 7 的差异可以由整数化规则复现：如果
true Top10% 使用 `floor(184×0.10)=18`，而预测预算仍取 10 条，则 F0 为 6 hits；
本报告统一使用 `ceil`，true positive 为 19 条，因此为 7 hits。该差异不是当前
F0 cutoff tie 的任意截断造成的。所有 floor/ceil 组合已写入
`rounding_sensitivity_trueTop10_predTop5`，后续必须先冻结整数化规则再比较模型。

## Within-parent 局限与信号

在每个 parent 内分别取 true/predicted Top20%，再对 6 个 score parents 做宏平均：

| 模型 | macro recall | macro EF |
|---|---:|---:|
| M2 | 37.5% | 1.65× |
| B seed43 | 41.0% | 1.79× |
| F0 ensemble | 36.1% | 1.58× |
| M2+F0 rank-mean | **49.3%** | **2.17×** |

这提示 M2/F0 的相对误差可能互补，但只有 6 个 parent，且 parent 大小不均。它
不能证明对新 scaffold 或 10 万库 sibling 排序稳定；至少需要完整 open nested
whole-parent folds 和 bootstrap CI。

## 对 10 万序列筛选的直接含义

当前 M2 与 F0 都不是纯序列零成本模型：

- M2 需要 126D VHH 单体结构/QC 特征；
- F0 需要 VHH residue ESM2、VHH 单体 residue graph，以及固定的 8X6B/9E6Y
  PVRIG graphs。

因此不应直接声称它们已经能经济地对 10 万条“只有序列”的库完整推理。推荐
分层部署：

```text
100,000 sequence candidates
  ↓ Fast QC + sequence-only student/cheap priors
10,000–20,000
  ↓ 批量单体结构/图特征 + M2/F0
2,000–5,000 structure-aware shortlist
  ↓ 共识 + OR + 分歧 + 多样性 portfolio
500–1,000 first-seed dual-receptor Docking
  ↓ 多 seed / cluster / full QC
最终 shortlist
```

structure-aware shortlist 的起始配额建议：

```text
60%  M2+F0 consensus/rank-mean
20%  M2/F0 best-rank OR 的单边高分候选
10%  M2–F0 高分歧/不确定性候选（主动学习）
10%  parent/patch/method/CDR3 多样性与随机 sentinel
```

这些比例是下一轮待验证的工程起点，不是已通过的生产权重。

## 下一步可执行项

1. **补齐 matched seed control**：运行 B seeds 97/193；F0 的 3-seed 优势不能与
   B 单 seed 直接解释为 contact 分支增量。
2. **覆盖完整 open inner folds**：为 M2/B/F0 产生 whole-parent cross-fitted
   predictions；用跨 fold macro EF/Recall 和 bootstrap CI 决定融合。
3. **严格 double cross-fit stacking**：inner-OOF 训练线性 meta-head，outer-open
   score 只评价；不得在同一 184 行拟合并报告。
4. **把 early enrichment 设为主指标**：冻结 0.5%、1%、2%、5%、10% 的整数化和
   tie-break；同时报告 global 与 within-parent Recall/EF。
5. **训练纯 sequence student**：蒸馏 M2/F0 与新增 Docking teacher，使 10 万库
   第一阶段不依赖全量单体结构。
6. **做 10 万规模吞吐基准**：分别测 ESM2 embedding、单体结构、M2 特征、F0
   推理的 rows/s、显存、失败率与 cache 体积，再冻结阶段预算。
7. **Docking 反哺采用分层主动学习**：高共识、高分歧、中分、低分、跨 parent/
   patch/method 随机 sentinel 都要补 Docking；不能只 Dock 当前模型 Top。
8. **F1 暂停**：当前 rank-loss F1 已明显退化，不进入召回融合。

## 文件

- `analyze_open_inner_ensemble_v1.py`：可复现分析；
- `METRICS.json`：完整单模型、融合、union、overlap、tie-aware 与 rounding sensitivity；
- `early_enrichment.tsv`：长表；
- `open_inner_predictions_and_fusions.tsv`：184-row 同 split 预测与固定融合；
- `INPUT_SHA256SUMS` / `OUTPUT_SHA256SUMS`：输入与输出哈希；
- `inputs/`：从 Node1 拉取的最小开放预测证据。

复现命令：

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  reports/pvrig_v2_6_open_inner_ensemble_audit_v1_20260719/\
  analyze_open_inner_ensemble_v1.py
```
