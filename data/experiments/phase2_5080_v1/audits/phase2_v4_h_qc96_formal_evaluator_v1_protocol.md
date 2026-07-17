# V4-H-QC96 one-shot formal evaluator V1：label-free 预注册协议

状态：`FROZEN_LABEL_FREE_BEFORE_V4_H_MANIFEST_PREDICTIONS_OR_DOCKING_LABELS_ARE_BOUND`

## 1. 目标与证据边界

本协议只评估：

```text
冻结的 VHH sequence surrogate
→ 预测连续 R_dual_min
→ 与独立 8X6B / 9E6Y Docking 的连续几何结果做一次性 prospective 对照
```

它不是 PVRIG 结合概率、Kd、competition、实验阻断、Docking Gold 或最终提交裁决。

## 2. V4-H estimand

V4-H 的 estimand 是：

> 在 H0–H4 冻结协议定义的、通过 Full-QC 的新 parent PVRIG-conditioned design universe 中，冻结 contact-family surrogate 对连续 `R_dual_min` 的前瞻性排序与校准性能。

评估样本不是原始 1,440 条生成序列，而是 H4 在完全不看模型和 Docking 的前提下冻结的 96 条：

```text
前四个 queue-ordered QC_CAPACITY_READY parents
× 3 patches
× 2 modes
× 每个 parent×stratum 4 条
= 96
```

因此结论只条件化到 QC-qualified new-parent design universe，不外推到未通过 QC 的生成序列、天然大库、任意未生成序列空间或实验阻断。

## 3. 与 H0–H4 的边界

H0–H4 分支拥有候选生成、Fast-QC、Full-QC、capacity gate 和最终 manifest。Formal 分支不修改这些规则，也不提前假定 manifest 哈希。

未来 formal 输入按以下顺序绑定：

1. H4 输出 immutable `qc96_manifest_v1.tsv`、audit、receipt；
2. 冻结 surrogate 模型、配置、96 行预测、prediction audit/receipt；
3. 冻结独立 V4-H evaluator 实现、adversarial tests、implementation freeze 和 runtime trust；
4. 只有上述 gate 全部通过后，才允许独立 8X6B/9E6Y Docking label release；
5. evaluator 在真正 unseal 前原子创建 one-shot lock；
6. 一次执行后，无论 PASS、FAIL 或 INSUFFICIENT，不能在同一版本下调参重跑。

当前阶段只允许 preregistration、protocol、non-executable input template 和 label-free tests；没有 evaluator、implementation freeze、runtime trust、one-shot lock 或 formal output。

## 4. 原样继承 V4-F V2 的科学合同

来源：

```text
phase2_v4_f96_formal_evaluator_v2_preregistration.json
SHA256 05d5727c7568ac9563c75d7ec7b916f172eefd915a728b829d29c25a12079fc3
```

V4-H 只改变面板身份、estimand 和 versioned artifact schema；以下科学门槛不变：

| 项目 | V4-H V1 冻结值 | 与 V4-F V2 关系 |
|---|---:|---|
| primary endpoint | `R_dual_min` | 相同 |
| primary family | `contact` | 相同 |
| overall Spearman | `>= 0.30` | 相同 |
| parent-bootstrap Spearman 95% CI lower | `> 0` | 相同 |
| parent-macro Spearman | `>= 0.20` | 相同 |
| nonnegative parent Spearman | `>= 3` | 相同 |
| Recall@exact 20% budget | `>= 0.50` | 相同 |
| EF@Top10% | `>= 3.0` | 相同 |
| EF@Top10% parent-bootstrap CI lower | `> 1.0` | 相同 |
| selective-risk MAE reduction | `>= 0.10` | 相同 |
| high/low uncertainty quartile MAE ratio | `>= 1.25` | 相同 |
| shortcut delta，若预先冻结 comparator 存在 | overall `>=0.05` 且 nonnegative parents `>=3` | 相同 |
| NDCG | 报告，无 standalone pass threshold | 相同 |
| MAE | 报告，无 absolute standalone pass threshold | 相同 |

### 分母与重复

| 项目 | 冻结值 |
|---|---:|
| Full-QC hard pass minimum | 64 |
| analyzable minimum | 64 |
| analyzable / Full-QC hard pass | `>=0.80` |
| parent clusters | `>=4` |
| analyzable per parent | `>=8` |
| valid parent-bootstrap replicates | `>=0.80` |
| bootstrap replicates / seed | `10,000 / 20260717` |
| Docking seeds | `917, 1931, 3253` |
| successful seeds per candidate per receptor | `>=2` |

Technical failure 保留在 Full-QC hard-pass denominator，`R_dual_min` 必须为空并带 nonempty reason；禁止 imputation，只有可计算 metrics 排除该行。

## 5. Panel 与缺失处理

- H4 panel 必须为 96 行、4 个新 parent、每 parent 24 条、六个 stratum 各 4 条。
- H4 freeze 后绝对禁止 replacement、parent substitution 或 score-based substitution。
- 若少于四个 parent 达到 capacity gate，状态是 `FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY`，不得 Docking。
- 若 H4 已冻结但 independent dual-Docking technical coverage 低于 64、低于四个 parent、每 parent 低于 8 或 bootstrap validity 不足，formal 结果只能是 `INSUFFICIENT_TECHNICAL_COVERAGE`。
- 不得以降低 gate、补候选、重跑“更漂亮”的 seeds 或修改 missingness 规则修成 PASS。

## 6. One-shot 与 label access

截至本预注册冻结时：

```text
V4-D test32 label files opened = 0
V4-F label files opened         = 0
V4-H label files opened         = 0
accepted label paths            = 0
formal evaluator executed       = false
one-shot lock created           = false
```

未来 evaluator 必须先完整验证 panel 和 prediction freeze，再接受 eligibility/Docking-label receipt。任何 prediction gate 失败必须发生在 label path 被打开之前。

## 7. 停止条件

当前准备工作在以下四类文件通过 label-free tests 后停止：

1. versioned preregistration；
2. 本协议；
3. non-executable、全占位符的 future-input template；
4. 对 V4-F V2 科学合同逐项等价的测试。

本阶段不得创建 evaluator、one-shot lock、formal output 或 label receipt。
