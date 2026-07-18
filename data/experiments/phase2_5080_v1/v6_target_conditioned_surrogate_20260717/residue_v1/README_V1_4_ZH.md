# residue_v1 V1.4：严格冻结 bootstrap 收集矩阵

V1.4 是 V1.3 的预生产修正版。它不修改 V1.3 trainer、collector 或 freeze 的任何字节。

## 审计结论

冻结的 `PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json` 已规定：

```text
bootstrap_repetitions = 1000
```

但 V1.3 collector 的命令行默认值为 2000，底层仅要求重复次数不少于 100。因而 V1.3
虽然验证了 amendment 的值，却没有强制实际运行参数与之相等。V1.3 被标记为
`SUPERSEDED_PREPRODUCTION`，不能用于生产汇总。

amendment 未冻结 bootstrap seed。V1.4 为确保可重现性，在新的 collector matrix 中冻结：

```text
bootstrap_repetitions = 1000
bootstrap_seed = 20260718
```

## V1.4 fail-closed 行为

- collector parser 默认 repetitions=1000、seed=20260718；
- `collect()` 在读取任何训练表、freeze、governance 或 outer-run 文件之前验证矩阵；
- repetitions=999、2000 或任意其他值均失败；
- 非 20260718 seed 均失败；
- `parent_bootstrap()` 同样重新验证矩阵，不能绕过生产入口；
- V1.4 trainer 和 collector 都验证 freeze 内的完整 collector matrix 及其 canonical SHA256；
- 最终 `OOF_PROMOTION_REPORT.json` 同时记录 matrix、matrix SHA、实际 repetitions 和 seed。

## 入口

```text
src/train_nested_residue_surrogate_v1_4.py
src/collect_residue_oof_v1_4.py
IMPLEMENTATION_FREEZE_V1_4.json
RESIDUE_V1_4_CONTRACT.json
```

生产 collector 不需要显式覆盖默认值；即使显式传参，也只能使用：

```bash
--bootstrap-replicates 1000 --bootstrap-seed 20260718
```

当前版本仅完成本地 CPU 契约验证，未启动任何远程训练或收集。
