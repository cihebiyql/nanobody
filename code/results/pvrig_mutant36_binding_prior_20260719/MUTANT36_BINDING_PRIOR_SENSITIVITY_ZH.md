# PVRIG 36 条亲本/突变体结合先验敏感性测试（2026-07-19）

## 结论

- 面板包含 7 条已知阳性亲本和 29 条局部突变体；三路模型 36/36 成功输出。
- **序列分类先验不是完全无效**：14 条预期破坏性 CDR3 突变中，DeepNano 对 10/14 给出下降，NanoBind-seq 对 11/14 给出下降。
- 但下降幅度较小，而且保守 CDR3 突变也经常下降，因此只能视为局部、弱方向信号，不能作为亲和力 hard gate。
- **NanoBind-affi 基本不敏感**：14 条破坏性突变仅 1 条预测变弱，多数区间完全相同；当前不能用于 PVRIG Kd 排序。
- 这些突变体没有实验结合标签，所以该结果是方向敏感性压力测试，不等同于真实 AUROC 或生物学阴性验证。

## 破坏性突变相对各自阳性亲本（14 对）

| 模型 | 预测变弱数 | 比例 | 平均变化（突变-亲本） | 中位变化 |
|---|---:|---:|---:|---:|
| DeepNano | 10/14 | 0.714 | -0.0058 | -0.0059 |
| NanoBind-seq | 11/14 | 0.786 | -0.0626 | -0.0592 |
| 简单均值共识 | 11/14 | 0.786 | -0.0342 | -0.0382 |
| NanoBind-affi 区间中点 pKd | 1/14 | 0.071 | 0.0225 | 0.0000 |

## 区分破坏性突变与保守对照的探索性 AUC

这里以“相对亲本下降越多”作为破坏性分数；仅用于该合成突变面板的方向压力测试。

| 模型 | 破坏性 vs 保守 CDR3 | 破坏性 vs framework |
|---|---:|---:|
| DeepNano | 0.745 | 0.582 |
| NanoBind-seq | 0.714 | 0.786 |
| 简单均值共识 | 0.765 | 0.776 |

## 各突变类别摘要

`低于亲本` 表示模型对突变体给出比对应阳性亲本更低的结合/亲和力先验。

| 突变类别 | n | 模型 | 低于亲本 | 高于亲本 | 平手 | 平均变化 |
|---|---:|---|---:|---:|---:|---:|
| single_conservative_cdr3 | 7 | DeepNano | 2 | 5 | 0 | 0.0082 |
| single_conservative_cdr3 | 7 | NanoBind-seq | 5 | 2 | 0 | -0.0039 |
| single_conservative_cdr3 | 7 | 简单均值共识 | 5 | 2 | 0 | 0.0022 |
| single_conservative_cdr3 | 7 | NanoBind-affi 区间中点 pKd | 2 | 0 | 5 | -0.0430 |
| single_aromatic_to_alanine_cdr3 | 7 | DeepNano | 6 | 1 | 0 | -0.0119 |
| single_aromatic_to_alanine_cdr3 | 7 | NanoBind-seq | 6 | 1 | 0 | -0.0853 |
| single_aromatic_to_alanine_cdr3 | 7 | 简单均值共识 | 6 | 1 | 0 | -0.0486 |
| single_aromatic_to_alanine_cdr3 | 7 | NanoBind-affi 区间中点 pKd | 1 | 1 | 5 | 0.0107 |
| multi_cdr3_alanine_scan | 7 | DeepNano | 4 | 3 | 0 | 0.0003 |
| multi_cdr3_alanine_scan | 7 | NanoBind-seq | 5 | 2 | 0 | -0.0399 |
| multi_cdr3_alanine_scan | 7 | 简单均值共识 | 5 | 2 | 0 | -0.0198 |
| multi_cdr3_alanine_scan | 7 | NanoBind-affi 区间中点 pKd | 0 | 1 | 6 | 0.0342 |
| single_conservative_framework | 7 | DeepNano | 4 | 3 | 0 | -0.0052 |
| single_conservative_framework | 7 | NanoBind-seq | 2 | 5 | 0 | 0.0126 |
| single_conservative_framework | 7 | 简单均值共识 | 3 | 4 | 0 | 0.0037 |
| single_conservative_framework | 7 | NanoBind-affi 区间中点 pKd | 0 | 1 | 6 | 0.0342 |
| known_20_family_cdr3_stability_delta | 1 | DeepNano | 0 | 1 | 0 | 0.0117 |
| known_20_family_cdr3_stability_delta | 1 | NanoBind-seq | 0 | 1 | 0 | 0.1491 |
| known_20_family_cdr3_stability_delta | 1 | 简单均值共识 | 0 | 1 | 0 | 0.0804 |
| known_20_family_cdr3_stability_delta | 1 | NanoBind-affi 区间中点 pKd | 0 | 0 | 1 | 0.0000 |

## 综合处置

1. DeepNano、NanoBind-seq：保留为独立弱 binding prior 和分歧/主动学习特征。
2. 不将二者直接解释为 Kd，不单一 hard fail，不覆盖 Docking blocker-like geometry。
3. NanoBind-affi：保留原始审计列，但从正式排序和前筛阈值中排除。
4. 在获得实验阴性或明确失活突变前，不把该面板 AUC 当作真实泛化性能。

## 解释限制

- `single_aromatic_to_alanine_cdr3` 和 `multi_cdr3_alanine_scan` 是预期破坏性控制，但没有实测 Kd/IC50，因此不能把它们全部直接当作真实阴性。
- 正式分类校准仍需要实验阴性、非相关 VHH 或有明确失活数据的突变体。
- Docking blocker-like geometry 与通用 binding prior 必须保持独立。

## 产物

- `mutant36_joined.tsv`
- `mutant36_evaluation_metrics.json`
- `run/`（原始输出、日志、时间、收据）
