# V2.6 排序与标度校准核心 V1.1

V1.1 是对已冻结 V1 的新增版本，不修改或追溯替换 V1。它只修复两个审查问题：

1. PairLogit 训练曾使用 normalized-softmin，但生产推理使用 exact-min；
2. 来自非自适应 V4-D 三 seed 的统一 `delta_noise` 不应直接外推到自适应抽样的 V4-H。

## 冻结修正

### 1. 排序和推理统一为 exact-min

模型仍只直接预测 `R8` 和 `R9`，但排序辅助损失现在使用：

```text
predicted_Rdual_for_rank = torch.minimum(predicted_R8, predicted_R9)
predicted_Rdual_for_inference = min(predicted_R8, predicted_R9)
```

`torch.minimum` 几乎处处可微；非相等时梯度只流向限制性 receptor，相等点按 PyTorch 的确定性子梯度处理。V1.1 不再允许 typed softmin batch 进入 PairLogit。因此排序损失优化的量与生产排序量完全相同，不需要依赖经验性的 no-sign-flip 假设。

Normalized-softmin 仍可由上游作为连续 dual 辅助回归损失使用，但它不再参与 V1.1 PairLogit，也不得被报告为生产 `Rdual`。

### 2. 保守的 source/tier rank eligibility

全部 1,507 条开放 teacher 仍可用于 `R8/R9` scalar 回归；仅 rank auxiliary 收紧：

| 来源/层级 | scalar | PairLogit | 原因 |
|---|---:|---:|---|
| V4-D / A / multi-seed | 是 | 是 | `delta_noise` 正是从独立、非自适应 V4-D 三 seed 候选估计 |
| V4-H / A / adaptive 3-seed | 是 | 否 | 多 seed 但抽样由首 seed 排名自适应触发，尚无 source-specific 随机 sentinel noise |
| V4-H / B / adaptive 2-seed | 是 | 否 | 同上，且重复更少 |
| V4-H / C / adaptive 1-seed | 是 | 否 | 无候选级 test-retest 方差 |

这不是把 V4-H 当成低质量 scalar 数据；它只表示：在随机 sentinel 估计出 V4-H source/tier-specific noise 之前，不能把 V4-D 的 `delta_noise` 当作 V4-H PairLogit 的统一测量误差阈值。

Pair cache 会显式保存 policy id、纳入/排除候选计数及排除原因；V4-H 行即使伪装为 tier A、或 V4-D 行的 source/tier/provenance 任一字段不匹配，也不会进入 rank pairs。

## 真实 1,507 条审计

`audit_real1507_rank_eligibility_v1_1.py` 只读取开放开发 teacher 和已冻结 whole-parent inner manifest：

- teacher SHA256：`47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1`；
- 1,507 candidates，31 parents；
- V4-D：226 / 20 parents，全部属于同一非自适应 A multi-seed source（225 条为 3/3 receptor seeds，1 条为 2/3）；V1.1 主 policy 保留全部 226，严格 225-only 可作为预注册 sensitivity challenger；
- V4-H：1,281 / 11 parents，A=123、B=241、C=917，全部 scalar-only；
- 全数据 V4-D same-parent unordered pairs：1,230；
- 通过 `|exact-min truth delta| >= delta_noise`：824；丢弃 406；
- 25 个 outer/inner TRAIN 分区中 rank-eligible parents 最少 10，满足每 step 8 个不同 parent；
- V4-F/test32 访问：0。

## 文件

- `rank_calibration_core_v1_1.py`：exact-min PairLogit、source/tier policy、cache、校准；
- `test_rank_calibration_core_v1_1.py`：单元、mutation、梯度和 deterministic cache tests；
- `audit_real1507_rank_eligibility_v1_1.py`：真实数据 source/tier/split 审计；
- `test_audit_real1507_rank_eligibility_v1_1.py`：真实审计和 mutation tests；
- `REAL1507_RANK_ELIGIBILITY_AUDIT.json`：真实审计结果；
- `IMPLEMENTATION_FREEZE_V1_1.json`、`TEST_RESULTS.log`、`SHA256SUMS`：冻结和哈希闭包。

## 证据边界

这些工具仅逼近独立双受体 Docking 的连续计算几何，不是结合概率、Kd、实验阻断概率、Docking Gold、sealed V4-F 证据或提交真值。
