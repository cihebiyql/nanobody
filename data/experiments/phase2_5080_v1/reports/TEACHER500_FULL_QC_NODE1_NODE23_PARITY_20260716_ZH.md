# Teacher500 Full-QC Node1/Node23 规范化一致性审计

## 结论

Node1 独立 scaled replicate 与 Node23 accelerator replicate 达到：

```text
PASS_NORMALIZED_DECISION_PARITY
```

Node23 输出现在可以作为 Teacher500 Full-QC 的规范版本。该结论表示跨节点计算 QC 和候选决策可复现，不表示实验结合、Kd、表达、纯度或阻断结果。

## 输入

Node1：

- `/data/qlyu/projects/pvrig_competition_teacher500_full_qc_v1_scaled_20260715/cascade/fast_merged.tsv`
- `/data/qlyu/projects/pvrig_competition_teacher500_full_qc_v1_scaled_20260715/cascade/full_merged.tsv`

Node23 本地同步版本：

- `experiments/phase2_5080_v1/runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/cascade/fast_merged.tsv`
- `experiments/phase2_5080_v1/runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/cascade/full_merged.tsv`

## 实测结果

| 层级 | Node1 | Node23 | 规范化结果 |
|---|---:|---:|---|
| Fast 输入/输出 | 500 | 500 | candidate ID 与顺序完全一致 |
| Fast hard-pass | 327 | 327 | 完全一致 |
| Full-QC 行数 | 327 | 327 | candidate ID 与顺序完全一致 |
| Full hard-pass | 302 | 302 | 完全一致 |
| Full hard-fail | 25 | 25 | 完全一致 |
| hard-pass + complete AbNatiV | 290 | 290 | 完全一致 |
| hard-pass + AbNatiV unscorable | 12 | 12 | 完全一致 |

以下决策字段逐候选、逐字符串完全一致：

- `candidate_id`、`sequence`
- `official_validator_pass`、`ANARCI_status`
- `IMGT_CDR1/2/3`
- `hard_fail`、`recommendation`
- `developability_score`
- `expression_purity_risk_score`
- `final_score`
- `cascade_full_rank`

因此，25 条 hard-fail、302 条 hard-pass、290 条 V4-D 主候选以及 12 条 review-only 候选集合均不受节点选择影响。

## 允许的规范化差异

### 1. `rank`

- Fast：493/500 行不同
- Full：277/327 行不同

这是 chunk-local 排名，受分块与 worker 完成顺序影响，不是最终跨候选排名。最终 `cascade_full_rank` 完全一致，因此不能把 chunk-local `rank` 当作下游选择依据。

### 2. `intra_team_cluster_id`

- Fast：375/500 行不同
- Full：227/327 行不同

这些值是 `DEFERRED_*` 的执行顺序标签。cluster size、候选决策和最终分数均一致，因此只忽略标签本身，不忽略实际候选、序列或决策字段。

### 3. `AbNatiV_VHH_score`

- 220/327 行存在浮点尾数差异
- 最大绝对差：`1.583195473608967e-07`
- 冻结容差：`1e-6`
- score 是否存在的掩码完全一致

这 220 个浮点差异没有改变 hard-fail、recommendation、开发性分、表达/纯度风险分、final score 或最终候选集合。12 条 unscorable 候选在两节点完全相同，均来自 parent `PLDNANO_VHH_00220`，继续保持 review-only，不进入主 290 集合。

## 可重放实现

脚本：

- `experiments/phase2_5080_v1/src/audit_teacher500_full_qc_node1_node23_parity.py`

单元测试：

- `experiments/phase2_5080_v1/src/test_audit_teacher500_full_qc_node1_node23_parity.py`
- `3/3 PASS`

机器可读 receipt：

- `experiments/phase2_5080_v1/audits/teacher500_full_qc_node1_node23_parity_v1/node1_node23_normalized_parity_receipt.json`
- SHA-256：`19c1fc1ed9fd3b8e25e19f2ec16f0c717c25680cfe65b1ce40bcbf4f674ef784`

规范化规则是 fail-closed：除 `rank`、`intra_team_cluster_id` 和容差内 `AbNatiV_VHH_score` 外，任何字段差异都会使审计失败；所有决策字段必须精确一致。

更新后的 Node23 integrity audit：

- `experiments/phase2_5080_v1/runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/teacher500_full_qc_node23_integrity_audit.json`
- SHA-256：`99eb23be25520dc58a6fa6177a298cca4fb21c35d3062258ae282df1702477c9`
