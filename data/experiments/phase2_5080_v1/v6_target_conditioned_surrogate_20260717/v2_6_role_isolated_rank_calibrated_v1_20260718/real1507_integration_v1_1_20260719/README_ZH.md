# V2.6 real1507 role-isolated integration V1.1

状态：`FROZEN_IMPLEMENTATION_TESTED_NONLAUNCHING_CPU_ONLY`。

该版本新建于 V1 旁边，V1 字节保持不变。它只修复阻止 CUDA smoke 的三个问题：

1. `kappa=0.25` 同时冻结 `lambda_contact_shared=1.0`，每一步验证 post-lambda contact shared gradient 未越界；
2. calibration 要求每个 outer-train candidate 恰好具有 held-out inner fold 的 43/97/193 三个成员，并闭合 candidate、parent、fold、seed 和 outer-test 排除；
3. gradient accumulation 不再等权平均 microbatch，而按 scalar 的原始 hierarchy mass、contact 各组件的 hierarchy×tier×eligibility mass 精确合并，适用于不等 batch 和尾部 partial window。

此外，rank cache 必须读取提前冻结的外部 split/label trust anchor，运行时不能自签。已经从 SHA 固定的 1,507 teacher 和 30,140-row inner manifest 生成 25 个 partition anchor。训练 receipt 每步保留 parameter、scalar trajectory、optimizer、batch 和 rank-cache 哈希，并显式记录 physical/logical CUDA 映射。

当前仍未授权正式 nested training；下一关是独立代码审查和 Node1 GPU1 CUDA/BF16 real-data smoke。
