# V2.10 canonical 10,644 teacher

## 目的

将冻结的 legacy D0 3,054 条与 V29 canonical release 的 7,591 条 open weak labels 合并，并在联合数据上重新执行等长 CDR3、Hamming identity ≥80% 的连通分量隔离。

```text
3054 legacy D0
+ 6872 canonical train
+ 719 canonical development
= 10645 raw open union
- 1 newly quarantined development row
= 10644 final open teacher
  = 9849 train + 795 development
```

该teacher只近似独立双受体计算Docking几何，不代表结合、Kd或实验阻断。

## 关键访问边界

canonical TSV物理上包含 frozen-test 和既有 quarantine 标签。Adapter必须依次执行：

1. 读取并验证 candidate、sequence、parent、`canonical_model_split`、`training_label_status`；
2. 只允许 `canonical_model_split in {train, development}`；
3. 只允许 `training_label_status == WEAK_LABEL_AVAILABLE`；
4. 通过以上门后才把R8、R9、Rdual转换为浮点数。

因此 frozen、quarantine 和 TECHNICAL_NA 数值目标解析计数均固定为0。

## 生成命令

```bash
python src/build_canonical10644_primary_teacher_v1.py \
  --legacy-d0-tsv /path/primary_D0_teacher.tsv \
  --legacy-d0-sha256 898aa1c609c995b05d7fa323c93169db5589ed53c4a32c12795b75f27721866a \
  --legacy-d0-manifest /path/primary_D0_split_manifest.json \
  --legacy-d0-manifest-sha256 cc91b3d4f2115c179db5f8c0f1a7b19d97b48d1ecf99ffb5662eb1ca800192c8 \
  --canonical-tsv /path/pvrig_v29_sequence_docking_weaklabels.tsv \
  --canonical-tsv-sha256 2ffd88625a50b757f5a291a7bbea99632a39db636e8dba570dea890ea95945d4 \
  --canonical-release-receipt /path/RELEASE_RECEIPT.json \
  --canonical-release-receipt-sha256 2f5f9622802262ce67749ea0436653200e6dfbd077920b61c52b511fb63db8c6 \
  --output-dir /new/nonexistent/prepared_dir \
  --split-id v29_canonical_release_v1_joint_cdr3_D1
```

输出：

```text
primary_D1_canonical10644_teacher.tsv
primary_D1_canonical10644_split_manifest.json
joint_cdr3_quarantine.tsv
MATERIALIZATION_RECEIPT.json
SHA256SUMS
```

## 独立验证

```bash
python tests/verify_v2_10_canonical_release.py \
  --teacher-tsv prepared/primary_D1_canonical10644_teacher.tsv \
  --split-manifest prepared/primary_D1_canonical10644_split_manifest.json \
  --quarantine-tsv prepared/joint_cdr3_quarantine.tsv \
  --receipt-json prepared/MATERIALIZATION_RECEIPT.json \
  --sha256sums prepared/SHA256SUMS
```

Verifier独立重算行数、parent closure、exact-min、CDR3跨split边、quarantine排除和所有哈希。

## Stage0衔接

沿用V2.9 `run_sequence_stage0_expanded_v2_9.py`，不修改模型代码。ESM2 cache直接复用已完成的 `all13322` 650M/3B caches；teacher是cache的严格子集，不需重新计算embedding。
