# V2.6 排序与标度校准核心 V1

本目录实现 V2.6 的独立排序/校准核心，不读取外层指标，不启动远程训练，也不访问 V4-F/test32。

## 已冻结能力

1. `delta_noise=0.019614956149`
   - 只接受权威绑定件 SHA256：`0a613b87509699a28d134c02514b1240e50a06a5aefddb5ca4a9d8202cde0a0c`；
   - 权威 JSON 保留全精度 `0.01961495614856818`，实现值是预注册的 12 位小数表示；
   - 校验 schema、status、225 个非自适应 V4-D 三-seed候选、源文件哈希、V4-H 排除和 sealed-access=0。

2. 双受体目标
   - 训练和排序：FP32 normalized softmin，`tau=0.02`；
   - 推理和报告：`Rdual=exact_min(R8,R9)`；
   - 禁止独立第三个 Rdual 输出。

3. `ParentPairEpochCache`
   - 只接受 `TRAIN` 行；显式拒绝 forbidden/outer-test candidate；
   - 调用方必须提供已冻结的 expected split hash 和 label hash，内部重算不一致即 fail closed；
   - 同 parent 无序 pair，`|delta truth| < delta_noise` 丢弃；
   - 少于 8 个 eligible parents 时 fail closed；
   - parent deterministic round-robin，每 parent 暴露数差不超过 1；
   - 每个 scalar optimizer step **恰好 8 pairs / 尽量且当前契约强制 8 个不同 parent**；
   - parent 内先无放回，再确定性循环；
   - 持久化 split、label、eligible-pair、cache content hashes及重复/丢弃审计。
   - `load_parent_pair_epoch_cache()` 可重放审计并拒绝持久化文件篡改。

4. Noise-aware PairLogit
   - `tau_rank=0.03`；
   - `weight=min(|delta truth|/delta_noise,3)`；
   - 先 parent 内平均，再 parent 间平均；
   - 只接受由 direct R8/R9 构造的 typed `SoftminDualPredictionBatch`，接口层拒绝 raw mapping/exact-min；
   - 不在 loss 内计算 exact min。

5. Fold-local positive affine calibration
   - 只允许 `OUTER_TRAIN_INNER_OOF`；
   - R8/R9 分别拟合 `a*x+b`；
   - `a in [0.5,1.5]`，`b in [-0.1,0.1]`；
   - 目标：Huber(beta=0.03) + 0.10 identity shrinkage；
   - 支持不足、优化不收敛或无严格目标改善时使用可审计 identity fallback；
   - 校准后再取 exact min。

## 文件

- `rank_calibration_core_v1.py`：实现；
- `test_rank_calibration_core_v1.py`：synthetic、split-firewall 与 mutation tests；
- `IMPLEMENTATION_FREEZE_V1.json`：实现、绑定件和测试证据冻结；
- `TEST_RESULTS.log`：fresh unittest 输出；
- `SHA256SUMS`：内容哈希闭包（不自包含）。

## 证据边界

这些工具仅用于逼近独立双受体 Docking 的连续几何结果，不是结合概率、Kd、实验阻断概率、Docking Gold、sealed V4-F 证据或提交真值。
