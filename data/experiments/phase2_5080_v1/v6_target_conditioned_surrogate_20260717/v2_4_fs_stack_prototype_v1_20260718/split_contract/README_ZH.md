# V2.4 deterministic whole-parent nested split contract

## Canonical V3

```text
src/build_whole_parent_nested_splits_v3.py
prepared/whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4/
```

V1 因 candidate-count 优先可能形成 `12/4/4/4/4` inner parent counts，已标记 superseded；有效统计单位是 31 个 parent，因此不再用于新 base trainer。

外层严格沿用训练表现有 `outer_fold`。内层 V3 使用 capacity-constrained whole-parent LPT：

1. 每个 inner fold 的 parent capacity 预先固定为 floor/ceil；
2. 任意两个 fold 的 parent 数相差不超过 1；
3. 在 capacity 约束内，按 parent candidate 数降序放置；
4. 使用 `SHA256(seed, outer_fold, parent)` 确定性打破同值；
5. 优先选择 candidate load 最低的未满 fold。

## 强制门控

- 输入恰好闭合 31 parents；
- parent 不跨 outer fold/source；
- outer train/score parent 不交叉，并集为 31；
- inner train/score parent 不交叉；
- outer-score parent 不进入 inner；
- 每个 outer-train parent 恰好在一个 inner fold 中作为 score；
- inner parent counts 最大差值 ≤1；
- 每行绑定 input-table、train-parent、score-parent SHA256；
- 禁止 V4-F 输入、输出和行来源。

## 真实训练表交付

输入：1507 candidates、31 parents、5 outer folds。

```text
outer manifest rows: 7535
inner manifest rows: 30140
materialized readback validation: PASS
```

SHA256：

```text
input table:
47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1

outer manifest:
ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55

inner manifest:
b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073
```

实际 inner parent counts：

```text
outer0: 6/6/6/5/5
outer1: 5/5/5/5/4
outer2: 6/6/5/5/5
outer3: 5/4/4/4/4
outer4: 5/5/5/5/4
```
