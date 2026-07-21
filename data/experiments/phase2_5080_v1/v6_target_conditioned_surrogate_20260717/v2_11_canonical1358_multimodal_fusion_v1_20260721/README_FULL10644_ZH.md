# canonical10644 全量单体结构与 M2-126D 物化

## 目的

为下一阶段多模态融合提供与 V2.10 完全相同候选和 split 的单体结构特征：

```text
canonical10644 metadata
+ 四个冻结单体 manifest
→ candidate/sequence/PDB/SHA/CDR 唯一闭合
→ 旧 M2 同定义的 126D label-free 特征
```

本目录不运行 C2、target-attention、contact head 或模型训练。

## 已验证资产覆盖

| 单体来源 | canonical10644 命中 | manifest SHA256 |
|---|---:|---|
| V29 | 7,591 | `ca7a7e8aa784ddf7c0f9079d3700c5098159e1fd599253ea64ade04a2cb3fe9f` |
| V4I | 1,695 | `869b345f4aa4ede80869ccc178f638d9fa727709b01addc8da6b0533e5c3c2b8` |
| V4H | 1,169 | `e74b32d53d7a1fb2719d8b7e01b60bb2855553794607f011e14e0f5399fa8137` |
| V4D | 189 | `893556640293d15a240158d487c8607a4326b55dd7af5ece46aeb4f3890bf03c` |
| 合计 | **10,644** | exact `(candidate_id, sequence_sha256)` closure |

V29/V4H 位于 Node1 `/data1`；V4I/V4D 的冻结 portable bundle 位于只读 `/data`。launcher
只把派生 manifest、M2 表、receipt 和日志写到新的 `/data1/qlyu/projects/` 版本目录。

## 数据边界

`build_full10644_structure_manifest_v1.py` 从 teacher TSV 只投影以下字段：

```text
candidate_id
sequence_sha256
sequence
parent_framework_cluster
cdr1 / cdr2 / cdr3
```

它不会索引或解析 `R_8X6B`、`R_9E6Y`、`R_dual_min`。它也不打开 Docking pose。

闭合门包括：

1. teacher、split 和四个 source manifest 的冻结 SHA256；
2. candidate ID 与 sequence SHA 精确二元匹配；
3. 重新计算 sequence SHA256；
4. PDB 是普通文件，并重新计算 monomer SHA256；
5. CDR1/2/3 在全长序列中各自唯一精确出现；
6. CDR 顺序正确且互不重叠；
7. parent 只能属于冻结 train 或 development split。

## M2 特征

`materialize_full10644_m2_features_v1.py` 复现旧 M2 的 126D 定义：

- ALL、FRAMEWORK、CDR1、CDR2、CDR3、CDR_ALL 六个区域的 19 项几何/置信度统计；
- 三组 CDR–CDR centroid distance；
- 三组 CDR–framework centroid/minimum/median-minimum distance。

全部是刚体不变、label-free 的单体特征。每条候选提取前再次验证 PDB SHA256。

## Node1 launcher

部署时将下列三个文件放到：

```text
/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/code/
```

- `build_full10644_structure_manifest_v1.py`
- `materialize_full10644_m2_features_v1.py`
- `test_full10644_structure_m2_v1.py`

随后运行：

```bash
bash launchers/run_full10644_m2_node1_v1.sh
```

预期输出：

```text
/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/
├── full10644_features/
│   ├── canonical10644_structure_manifest_v1.tsv
│   ├── canonical10644_structure_manifest_v1.receipt.json
│   ├── canonical10644_m2_126d_features_v1.tsv
│   └── canonical10644_m2_126d_features_v1.receipt.json
└── status/TERMINAL.json
```

只有 `PASS_FULL10644_M2_TERMINAL` 才表示全量物化完成；它不表示模型性能提升。
