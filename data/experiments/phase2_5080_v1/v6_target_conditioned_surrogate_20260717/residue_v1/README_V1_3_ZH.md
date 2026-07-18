# residue_v1 V1.3：最终 governance / outer-binding 闭包

V1.3 在不修改 V1.2 代码和 freeze 字节的前提下，修复 collector 的最终 P0。

## Governance 硬门

训练器和独立 OOF collector 均要求：

```text
--governance-amendment ../PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json
```

并 fail closed 验证：

- 普通文件且不是 symlink；
- SHA256 必须为
  `dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226`；
- schema 必须为 `pvrig_v6_implementation_amendment_v1_1`；
- status 必须为
  `FROZEN_BEFORE_ANY_NODE1_V6_MODEL_SMOKE_OR_PRODUCTION_TRAINING`；
- promotion gate 字符串必须完全一致；
- bootstrap repetitions 必须为 1000。

`IMPLEMENTATION_FREEZE_V1_3.json` 内的 `governance.path`、`sha256` 和 promotion gate
也必须与传入文件完全闭合。

## Outer run 闭包

collector 对每个 outer fold 同时验证：

```text
contract.binding.external_hashes.implementation_freeze_sha256
== collector 使用的 V1.3 freeze SHA256

result.binding_hash
== seal.binding_hash
== contract.binding_hash
```

另外验证 contract、prediction、RESULT 的内容哈希，以及 contract 中的 implementation
hash map 与 collector freeze 完全一致。任一 outer contract、result、seal 或 freeze 被替换，
collector 都会拒绝汇总。

## 入口

```text
src/train_nested_residue_surrogate_v1_3.py
src/collect_residue_oof_v1_3.py
IMPLEMENTATION_FREEZE_V1_3.json
```

collector 新增必需参数：

```bash
--governance-amendment /path/to/PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json
```

当前仍未启动远程训练。

