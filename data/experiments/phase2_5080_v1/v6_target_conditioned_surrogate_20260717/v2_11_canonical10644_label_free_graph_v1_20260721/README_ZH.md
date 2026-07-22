# V2.11 canonical10644 label-free VHH graph 第一步

## 状态

`IMPLEMENTED_PREPARE_ONLY_NOT_LAUNCHED`

本目录实现下一安全模态的第一步，但**没有启动 10,644 条结构图物化**，不会与当前 C2 32CPU 作业争用资源。

## 安全边界

- 复用 `residue_v2/src/build_residue_graph_cache_v2.py`；builder SHA256 由 `INPUT_CONTRACT.json` 冻结。
- canonical candidate 表只读取 `candidate_id / sequence / sequence_sha256 / cdr1 / cdr2 / cdr3`。
- structure manifest 必须逐行闭合 `candidate_id + sequence_sha256 + monomer_sha256`，且其文件 SHA256 必须由调用方显式提供。
- structure manifest 只允许单体 PDB 路径、hash、chain、size 等白名单字段；出现 contact、pose、Docking、teacher、score、result、complex 字段即失败。
- monomer 路径必须为安全相对 `.pdb` 路径，且不得包含 Docking/contact/pose/result 等 token。
- 固定 8X6B/9E6Y target graph 只做 receipt/artifact hash 复验，不重建。
- 不读取或生成 contact teacher、candidate Docking pose、Docking result、pose-derived feature。

## 为什么还没有生产运行

当前本地存在：

- V29 冻结 monomer manifest；
- 旧 supervised1507 graph closure；
- 固定 8X6B/9E6Y target graphs。

但当前仓库**没有交付覆盖 canonical10644 全部 10,644 行的统一 structure manifest**。V4I 等新增行仍需从其已闭合 monomer 资产汇总成统一、只含 label-free 字段的 manifest。适配器不会用缺失行、旧 contact teacher 或 Docking pose 补齐。

## 两阶段使用

### 1. 轻量 prepare

```bash
MANIFEST=/path/to/frozen_canonical10644_structure_manifest.tsv
# 必须来自已经冻结的 structure-manifest receipt；不要在启动时对任意文件
# 现算 hash 并把它当成“已闭合”证据。
MANIFEST_SHA256=<sha256_from_frozen_structure_manifest_receipt>

./launch_canonical10644_label_free_graph_v1.sh prepare \
  --structure-manifest "$MANIFEST" \
  --expected-structure-manifest-sha256 "$MANIFEST_SHA256" \
  --output-dir /path/to/canonical10644_label_free_graph_v1
```

该步骤只生成：

- `canonical10644_label_free_graph_input_manifest_v1.tsv`
- `PREPARE_RECEIPT.json`

不会打开 10,644 个 PDB，也不会生成 graph cache。

### 2. 显式 materialize（当前未执行）

```bash
export PVRIG_ALLOW_CANONICAL10644_GRAPH_MATERIALIZATION=1
./launch_canonical10644_label_free_graph_v1.sh materialize \
  --output-dir /path/to/canonical10644_label_free_graph_v1 \
  --pdb-root /path/to/clean_label_free_monomer_bundle
```

materialize 会逐个重新计算实际 monomer SHA256，并由 residue-v2 builder 校验 sequence、单链 PDB、CDR region 与 monomer hash；BLAS/OpenMP 被限制为 1 线程。

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
