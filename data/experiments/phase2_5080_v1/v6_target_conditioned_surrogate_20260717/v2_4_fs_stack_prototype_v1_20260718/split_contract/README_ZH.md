# V2.4 deterministic whole-parent nested split contract

## 目的

为新的 receptor-specific base trainer 生成无 parent 泄漏的 outer development 和 inner OOF manifests。

外层划分不重算、不调优，完全沿用训练表中已有的 `outer_fold`。同一 parent 的所有 candidate 必须属于同一 outer fold。

每个 outer-train 内再确定性生成 inner folds：

```text
parent 按 candidate 数量降序
-> seed + outer fold + parent SHA256 打破同值
-> 依次放入 candidate load 最小的 inner fold
-> 再以 parent load、fold index 打破同值
```

全程以 parent 为不可拆分单位。

## 输出

```text
outer_development_manifest.tsv
inner_nested_oof_manifest.tsv
split_summary.json
receipt.json
```

两个 TSV 都逐 candidate 写出：

- `candidate_role=train/score`；
- teacher source、parent、candidate；
- outer fold，inner manifest 另含 inner fold；
- train/score parent-set SHA256；
- 输入训练表 SHA256；
- builder/algorithm 版本。

inner manifest 同时携带对应 outer-train 和 outer-score parent-set SHA256。

## 强制门控

- 输入必须恰好闭合 31 个 parent；
- parent 不得跨 outer fold 或 teacher source；
- outer train/score parent 不得重叠，且并集必须为全部 31 parents；
- 每个 outer-train parent 在 inner folds 中必须恰好作为 score parent 一次；
- outer-score parent 不得进入任何对应 inner split；
- 每个 split 的 candidate 集合必须闭合；
- 每行必须绑定输入表和 parent sets 的 SHA256；
- 输入、输出、source、candidate 或 parent 不得来自 V4-F 路径/命名。

## 运行

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  src/build_whole_parent_nested_splits_v1.py \
  --input-tsv v6_supervised1507.tsv \
  --inner-fold-count 5 \
  --inner-seed 1931 \
  --output-dir prepared/all_outer_v1
```

如只需要一个 outer development fold：

```text
--development-outer-fold 3
```

该目录只负责 split manifests，不训练模型。

## 当前真实训练表交付

已对 `v6_supervised1507.tsv` 生成并完成写盘后重新读取验证：

```text
prepared/whole_parent_nested_splits_all_outer_seed1931_v1/
```

结果：

```text
input candidates: 1507
input parents: 31
outer folds: 5
outer manifest rows: 7535
inner manifest rows: 30140
materialized readback validation: PASS
```

关键 SHA256：

```text
input table:
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633

outer manifest:
f10cd0f67988545faa6213b32d482c6a5c436c99c33e1a71c8ded13dd83795ea

inner manifest:
6886b710e37fa0e4c4d43946993f18860e372961662d31bc8424200e46a22cad
```
