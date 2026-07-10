# Phase 2 负样本设计

Updated: 2026-07-09

## 为什么负样本要单独设计

抗体-抗原数据里，大多数公开数据只告诉我们“哪些复合物/序列是阳性”，很少直接给 confirmed non-binder。直接随机拼 antibody-antigen pair 会引入 false negative，同时又可能太容易，导致模型在测试集上虚高。

因此 Phase 2 采用分层负样本：easy negatives + hard negatives + contact-map negatives + PVRIG-specific controls。

## 外部工作可参考的做法

| 参考 | 可借鉴点 | 对本项目的启发 |
| --- | --- | --- |
| AbAgIntPre, Frontiers in Immunology 2022, https://www.frontiersin.org/journals/immunology/articles/10.3389/fimmu.2022.1053617/full | 抗体-抗原 interaction prediction 中使用正负样本平衡，并从不同抗原/抗体组合构造 negative pairs | 可以先做 1:1 easy negative，保证 pair classifier 有基础判别能力 |
| NanoBinder, Journal of Cheminformatics 2025, https://jcheminf.biomedcentral.com/articles/10.1186/s13321-025-01035-4 | 面向纳米抗体 binding prediction，关注 nanobody-antigen 复合物结构和非结合/错配构造 | hard negative 应尽量保持结构/框架相似，不能只靠长度或物种差异作弊 |
| PPI prediction negative sampling 经验，例如 D-SCRIPT / PPI 文献 | 随机 non-interacting pairs 往往太容易，hard negatives 和 split 控制很重要 | 本项目评估必须单独报告 easy-negative 与 hard-negative 性能 |

## 负样本类型

### N0: residue-pair non-contact negatives

用途：训练 contact-map head。

定义：在真实 VHH-antigen 复合物中，VHH residue 和 antigen residue 的最小 heavy-atom 距离大于阈值，作为非接触 residue pair。

建议：

```text
positive contact: min heavy-atom distance <= 4.5 Å
gray zone: 4.5 Å < distance < 8.0 Å，不用于训练
negative contact: distance >= 8.0 Å
```

抽样比例：

```text
contact positive : contact negative = 1 : 3 到 1 : 5
```

采样时匹配 residue 类型和位置分布，避免模型只学会“边缘残基不接触”。

### N1: easy cross-antigen pair negatives

用途：训练 pair-level binder classifier 的基础负样本。

构造：

```text
保留 VHH_i
替换 antigen_j
要求 antigen_j 与 antigen_i 不同 cluster
要求不存在已知 VHH_i-antigen_j 阳性证据
```

建议比例：

```text
positive pair : N1 = 1 : 1
```

优点：稳定、简单、可大规模构造。

风险：太容易；模型可能学 antigen family 或长度，而不学真实 binding interface。

### N2: same-antigen-family hard negatives

用途：防止模型只靠抗原类别或长度作弊。

构造：

```text
VHH_i 绑定 antigen_i
选择 antigen_j 与 antigen_i 同 family / 同物种 / 高结构相似
但不是同一 epitope 或无已知结合证据
构造 VHH_i-antigen_j 作为 hard negative
```

如果无法可靠判定 same family，则使用 antigen sequence identity 或 antigen_name 规则近似。

建议比例：

```text
positive pair : N2 = 1 : 0.5 到 1 : 1
```

### N3: framework-similar / CDR-different hard negatives

用途：防止模型只识别 VHH framework，而忽略 CDR。

构造：

```text
固定 antigen_i
选择 VHH_j：framework 相似，但 CDR3 不同且无已知 antigen_i binding 证据
构造 VHH_j-antigen_i 作为 hard negative
```

约束：

```text
VHH full identity 可高
CDR3 identity 必须 < 50% 或来自不同 CDR3 cluster
```

### N4: docking/pose decoy negatives

用途：训练 blocker-like 或 contact quality head。

构造：

```text
同一 VHH-antigen pair 的非原生 pose
或 docking 后没有覆盖 PVRIG-PVRL2 interface 的 pose
```

标签：

```text
binder pair 仍可能为 positive
pose/contact/blocker geometry 为 negative 或 low-quality
```

注意：不要把 pose negative 误当成 pair-level non-binder。

### N5: PVRIG-specific negative/control set

用途：PVRIG 最终校准，不参与普通训练。

来源：

```text
model_data/pvrig_blocker_mutant_control_calibration_v0.csv
reports/mvp_pvrig_control_scores_v0.csv
后续 docking 后的 binder-like-C / evidence-only-E 候选
```

标签边界：

```text
known positive exact -> calibration positive / leakage anchor
near known positive -> holdout / manual leakage review
mutants -> robustness controls
binder-like nonblocking docking pose -> blocker negative, not necessarily binder negative
```

## 初始训练推荐比例

Phase 2 第一个可训练版本建议：

```text
pair-level:
  positive : N1 easy : N2 same-family : N3 framework-hard = 1 : 1 : 0.5 : 0.5

contact-map:
  contact positive : N0 non-contact = 1 : 4

PVRIG calibration:
  不参与训练，只参与最终 calibration/evaluation
```

## 负样本审计字段

每条负样本必须记录：

```text
negative_id
negative_type
source_positive_id
vhh_id
antigen_id
vhh_seq
cdr1_seq
cdr2_seq
cdr3_seq
antigen_seq
construction_rule
reason_not_positive
excluded_known_positive_hit
split
group_key
seed
notes
```

## 评估必须拆分报告

不能只报总 AUROC。必须分开报告：

| 评估集 | 目的 |
| --- | --- |
| easy-negative test | 检查基础 pair 区分能力 |
| hard-negative test | 检查模型是否真的学 interface |
| contact-map test | 检查 residue-pair 接触预测 |
| PVRIG external calibration | 检查 known positives / mutants / candidates 的排序边界 |

如果 easy-negative 分数很高但 hard-negative 很低，说明模型还不能用于 PVRIG 优化。
