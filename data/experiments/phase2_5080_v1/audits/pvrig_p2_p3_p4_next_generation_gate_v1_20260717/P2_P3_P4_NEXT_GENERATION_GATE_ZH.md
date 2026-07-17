# P2/P3/P4 下一批序列生成门审计

## 结论

**当前不得按 P2/P3/P4 富集结果生成下一批序列。**

审计本身成功完成，状态为 `PASS_FAIL_CLOSED_AUDIT`；但生成决策为：

```text
BLOCKED_NO_RELIABLE_P2_P3_P4_ENRICHMENT
```

这不是 Docking 流程失败。相反，固定 128 条候选的双构象评价器已经稳定通过；真正未通过的是随后预注册的 P2/P3/P4 富集门。

## 1. P2/P3/P4 到底是什么

P1–P6 是第一套 RFantibody 设计实验的 **generation phase / arm 分组**。例如 `arm_id=P2_qkg_L` 的 phase 是 P2。

它们不是：

- 8X6B 或 9E6Y；
- V4-E 的 `A_CENTER/B_LOWER/C_CROSS`；
- V4-E 的 `H3/H1H3`；
- `OPEN_TRAIN/OPEN_DEVELOPMENT`。

固定 128 条面板中的 phase 数量为：

| Phase | 候选数 |
|---|---:|
| P1 | 22 |
| P2 | 21 |
| P3 | 24 |
| P4 | 23 |
| P5 | 23 |
| P6 | 15 |

预注册分析把 P2、P3、P4 分别作为目标组，把 P1+P5+P6（共 60 条）作为共同比较组。

## 2. 评价器是否稳定

是。冻结评价器报告：

- `status=PASS`
- `unlockable=true`
- 1050 个任务全部进入终态；
- 1049 个任务成功并有 pose；
- 1 个任务为 `FAILED_MAX_ATTEMPTS`；
- 128/128 候选可评价；
- threshold sensitivity、双构象评分闭合、正/破坏性对照、模型数等全部 PASS。

本审计于 2026-07-17 在 Node23 用冻结脚本重新运行富集分析。退出码按预期为 1（因为富集门 FAIL），重新生成的 JSON 和 TSV 与冻结结果 **逐字节一致**：

- JSON SHA256: `420896c3660b51dee8990602146de20f39f19ce4706d8d5f00aebcd777181418`
- TSV SHA256: `797541a355466c8f151009659c0bfa851131ca035b2fe13549a6801ae2a31feb`

因此结果不是临时计算误差，也不是评价器尚未完成。

## 3. P2/P3/P4 实际富集结果

128 条中只有 5 条满足严格 robust-A 定义。比较组 P1+P5+P6 为 1/60（1.67%）。

| Phase | robust-A | 目标率 | 风险差 | 风险比 | Holm 校正 p | 是否合格 |
|---|---:|---:|---:|---:|---:|---|
| P2 | 1/21 | 4.76% | +3.10% | 2.86 | 0.9074 | 否 |
| P3 | 0/24 | 0.00% | -1.67% | 0.00 | 1.0000 | 否 |
| P4 | 3/23 | 13.04% | +11.38% | 7.83 | 0.1879 | 否 |

冻结门槛要求同时满足：

- phase 候选数 ≥15；
- coverage ≥0.90；
- robust-A rate ≥0.20；
- 风险差 ≥0.10；
- 风险比 ≥1.50；
- Holm 校正 p ≤0.10。

P4 有方向性信号，风险差和风险比达到门槛，但：

1. robust-A rate 只有 13.04%，低于 20%；
2. Holm 校正 p=0.1879，高于 0.10。

所以 **P4 只能作为弱探索信号，不能称为可靠富集，更不能据此解锁下一代生成**。P2 和 P3 也不合格。

## 4. 为什么不能把 open258 接到 P2/P3/P4

V4-E open258 属于另一套候选体系：

- `target_patch_id`: A_CENTER / B_LOWER / C_CROSS
- `design_mode`: H1H3 / H3
- `model_split`: OPEN_TRAIN 226 / OPEN_DEVELOPMENT 32

本审计做了双重身份核验：

- open258 与 V4-D open manifest：candidate_id 258/258 闭合；
- sequence_sha256：258/258 闭合；
- V4-C fixed128 与 V4-D open258 的 candidate_id 交集：0；
- V4-C fixed128 与 V4-D open258 的 sequence_sha256 交集：0。

因此没有合法的 `open258 -> P1-P6` bridge。按行号、parent_id、序列相似度或把 patch 名改写成 P2/P3/P4 都会制造伪谱系。

## 5. 当前正确动作

1. 保留 P2/P3/P4 生成门为关闭状态；
2. 不根据 P4 的弱方向性信号直接扩大生成；
3. 如果继续利用 V4-E open258，只能对其真实设计轴 A/B/C 与 H3/H1H3 做独立、明确标注为 retrospective/exploratory 的分析；
4. 任何新生成策略都需要新的预注册规则和独立候选/parent 级验证，不能声称通过了旧 P2/P3/P4 门；
5. Docking/teacher 分数仍是计算几何证据，不是结合、Kd、竞争或实验阻断结论。

## 6. 复现

在本目录执行：

```bash
python3 scripts/audit_pvrig_p2p3p4_lineage_gate.py \
  --v4c-manifest inputs/v4c_dual128_split_manifest.tsv \
  --v4d-manifest inputs/v4d_fullqc290_split_manifest.tsv \
  --v4e-teacher inputs/v4e_open258_research_teacher.tsv \
  --evaluator reports/EVALUATOR_STABLE.json \
  --enrichment reports/P2_P3_P4_ENRICHMENT.json \
  --enrichment-tsv reports/p2_p3_p4_enrichment.tsv \
  --out P2_P3_P4_NEXT_GENERATION_AUDIT_RECEIPT.reproduced.json
```

预期输出：

```text
PASS_FAIL_CLOSED_AUDIT
BLOCKED_NO_RELIABLE_P2_P3_P4_ENRICHMENT
new_sequence_generation_authorized=false
```

## 7. V4-E 真实设计轴的补充探索分析

在确认 open258 不能映射到 P1–P6 后，又对 open258 实际存在的两个设计轴做了独立分析：

- patch：A_CENTER / B_LOWER / C_CROSS；
- mode：H1H3 / H3。

方法边界：

1. 只在 OPEN_TRAIN 226 条上拟合 `R_dual_min` 的 75% 分位阈值；
2. 固定该阈值后，在 parent-disjoint 的 OPEN_DEVELOPMENT 32 条上评价；
3. sealed test32 完全未打开、未使用；
4. 该分析始终是 retrospective exploratory，不具有生成解锁权。

训练集阈值为 `R_dual_min >= 0.576615197`。训练集有 57/226（25.22%）达到该阈值，但开发集只有 1/32（3.13%）达到，且：

- 训练集 20 个 parent，分数均值 0.5420；
- 开发集仅 3 个 parent，分数均值 0.5036；
- 说明绝对 teacher 阈值存在明显 parent/scaffold 分布迁移。

开发集结果：

| 轴 | 水平 | 开发集 high | 相对其余组风险差 | Holm p | 独立 parent 数 | 探索信号 |
|---|---|---:|---:|---:|---:|---|
| patch | A_CENTER | 1/10 | +10.00% | 1.000 | 3 | 否 |
| patch | B_LOWER | 0/11 | -4.76% | 1.000 | 3 | 否 |
| patch | C_CROSS | 0/11 | -4.76% | 1.000 | 3 | 否 |
| mode | H1H3 | 1/20 | +5.00% | 1.000 | 2 | 否 |
| mode | H3 | 0/12 | -5.00% | 1.000 | 2 | 否 |

结论：

- 没有任何 patch 或 mode 达到探索性候选级信号门；
- 开发集只有 3 个独立 parent，低于预设的最少 5 个 parent；
- A_CENTER 在训练集方向较好，但开发集只有 1 个 high 候选，且 parent 内均值效应并非 3/3 同方向；
- H1H3 也只有很弱方向性，不能据此扩大生成。

因此补充分析同样输出：

```text
PASS_EXPLORATORY_ANALYSIS_NO_GENERATION_RELEASE
candidate_level_signals=[]
generation_authorized=false
```

对应机器可读结果为 `V4E_DESIGN_AXIS_EXPLORATORY_ANALYSIS.json`。
