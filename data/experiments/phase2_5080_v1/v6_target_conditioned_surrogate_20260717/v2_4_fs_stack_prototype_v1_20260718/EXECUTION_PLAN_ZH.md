# PVRIG V2.4-FS-STACK 执行计划

## 目标与边界

目标是从 VHH 序列、label-free VHH 单体结构以及固定的 8X6B/9E6Y
PVRIG 图，预测独立双受体 Docking 的连续几何量 `R_8X6B`、`R_9E6Y`，并严格派生：

```text
R_dual_min = min(R_8X6B, R_9E6Y)
```

该输出仅表示 computational Docking geometry surrogate，不表示结合概率、Kd、
实验阻断概率、Docking Gold 或提交真值。V4-F/test32 在预测冻结前保持 sealed。

## 当前可用开放监督

- V4-D：226 candidates，20 parent clusters；
- V4-H：1,281 analyzable candidates，11 parent clusters；
- 合计：1,507 candidates，31 parent clusters；
- V4-H adaptive repeat tiers：123 条三 seed、241 条两 seed、917 条单 seed；
- V4-H 39 条技术不完整项不进入监督表。

## V2.4 基础模型

### M2

保持 V2.3 的 126D label-free monomer features、weighted Ridge 和 whole-parent
cross-fitting 不变。M2 只作为独立 comparator/evidence branch，不进入 neural forward。

### Neural

```text
frozen ESM2-650M residue states
+ VHH AA/CDR-region embedding
+ label-free VHH invariant graph
+ fixed 8X6B/9E6Y PVRIG graphs
        ↓
shared rank-64 pair representation
        ├── attention routing logits
        └── calibrated contact logits
        ↓
direct R8/R9 prediction
        ↓
exact-min dual
```

Neural forward 禁止 `structure_features`、`m2_base`、parent/candidate/source ID 和
candidate Docking pose。

## 四卡开发矩阵

Node1 使用 GPU `1,2,4,5`，每个进程最多 8 CPU threads：

| GPU | Lane | 目的 |
|---:|---|---|
| 1 | `A_VHH_ONLY` | 匹配容量、无 PVRIG target 的 shortcut baseline |
| 2 | `B_TARGET_NO_CONTACT` | PVRIG target graph，但不使用 contact supervision |
| 4 | `C_SPLIT_MARGINAL` | 独立 attention/contact heads + marginal contact |
| 5 | `D_SPLIT_PAIR` | C + 高可靠性 pair-contact supervision |

四条 lane 使用相同 parent folds、随机种子和 scalar 标签。contact loss 权重必须在
正式 development OOF 前通过 open-only、optimizer-step 之前的梯度比例校准冻结；
不能沿用 V2.3 权重后直接声明正式结果。

## 逐阶段执行

1. **数据契约**：把 V4-H scalar 标签更新为 adaptive median，生成 1,507 行新表及
   A/B/C tier；验证 exact-min、parent fold、hash closure。
2. **模型单测**：split logits、feature firewall、exact-min、BF16 finite、gradient routing。
3. **Tiny E2E**：合成 parent 数据完成 train/eval/receipt 闭包。
4. **Smoke93**：四卡各跑一个 lane，验证真实 ESM2、图缓存、contact teacher 和显存。
5. **Open-only 梯度校准**：冻结 contact loss 权重和 attention temperature。
6. **Base development OOF**：whole-parent outer folds；输出 R8/R9、derived dual、
   receptor-specific contact summaries 和逐行 base-fit provenance。
7. **Double cross-fit stack**：只使用 inner-OOF 六列证据训练五参数非负共享斜率模型。
8. **一次性冻结评估**：失败则写 `DO_NOT_PROMOTE_V2_4_FS_STACK`，不修改同版本门限。

## 预定开发参数

- backbone：本地冻结 ESM2-650M；
- graph hidden：128；interaction rank：64；
- dropout：0.25；attention temperature primary：1.0；
- optimizer：AdamW，head LR `1e-4`，weight decay `0.02`；
- precision：BF16，所有 entropy/log/calibration reduction 使用 FP32；
- max epochs：8；gradient accumulation：2；gradient clip：1.0；
- primary scalar loss：R8/R9 Huber + exact-min auxiliary Huber；
- meta primary：6 input columns、5 free parameters；GBDT 只作 non-promotable exploration。

这些是 development defaults。只有代码、数据、测试和校准 receipt 哈希闭合后，才会
生成新的 implementation freeze 和正式 launcher。

## 停止条件

任一情况立即 fail closed：

- V4-F/test32 或其他 sealed artifact 被打开；
- neural forward 接受 M2/126D/ID/Docking pose；
- prediction dual 不等于 exact min；
- 任何非有限 loss、gradient、parameter 或 optimizer state；
- meta feature 是 in-sample base prediction；
- parent 出现在对应 base/meta training provenance；
- 运行后修改同版本 split、阈值、权重或 promotion gate。
