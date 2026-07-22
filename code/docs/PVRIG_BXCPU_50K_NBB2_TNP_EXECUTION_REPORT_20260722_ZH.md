# PVRIG 50k VHH：bxcpu 结构预测与 TNP 执行报告

日期：2026-07-22

## 1. 本轮已完成的计算

以冻结的 50,000 条 provisional prestructure 候选为输入，在 bxcpu 上完成：

1. NanoBodyBuilder2 单体结构预测；
2. 结构文件、manifest 和节点归档校验；
3. TNP 官方结构指标的复用式部署；
4. 50,000 条批量 TNP 计算；
5. selection、binding prior、AbNatiV、Sapiens、序列风险、NBB2 和 TNP 的统一 50k 表；
6. bxcpu → 本地的校验传输；
7. Node1 自动重试同步。

## 2. bxcpu 资源与作业

### NanoBodyBuilder2

- 8 个节点；
- 每节点申请 64 CPU；
- 每节点 16 个常驻 worker，每 worker 4 threads；
- 初始作业：`11939532`；
- 原脚本错误修复后的可恢复重跑：`11939594`；
- 最终聚合：`11939595`。

最终结构状态：

| 状态 | 数量 |
|---|---:|
| `SUCCESS` | 49,840 |
| `TECHNICAL_NA` | 160 |
| 总计 | 50,000 |

160 条 `TECHNICAL_NA` 均为 NanoBodyBuilder2 的“序列缺少过多可编号残基”技术拒绝，不是低结合、低亲和力或非阻断标签；后续正式结构池应剔除或单独修复这些序列。

### TNP

- 8 个节点；
- 每节点 64 CPU worker；
- 批量作业：`11939616`；
- 聚合作业：`11939617`；
- 每节点 6,250 条；
- 每节点耗时约 93–97 秒。

最终 TNP 状态：

| 状态 | 数量 |
|---|---:|
| `PASS` | 49,840 |
| `TECHNICAL_NA` | 160 |
| 总计 | 50,000 |

TNP 的 160 条 NA 与 NBB2 缺失结构完全对应。

## 3. 修复的两个工程问题

### 3.1 ImmuneBuilder/OpenMM Threads 参数错误

ImmuneBuilder 1.2 的 strained-sidechain recovery 路径把 OpenMM platform properties 写成 Python `set`：

```python
{'Threads', str(n_threads)}
```

OpenMM 实际要求 `dict`：

```python
{'Threads': str(n_threads)}
```

该错误曾造成数千条有效预测在精修阶段成为技术失败。已使用 exact-match、幂等 patch 修复，并在一个真实失败候选上重新精修成功，PDB 序列与输入完全一致。

修复收据：

```text
$HOME/pvrig_bxcpu_model_runtime_v1_20260721/status/IMMUNEBUILDER_OPENMM_THREADS_PATCH.json
```

### 3.2 TSV 记录数误用 `wc -l`

原归档脚本用 `wc -l` 判断 manifest 记录数。异常文本含换行时，一个合法 CSV record 会占多行，导致节点被误判为记录超额。已改为 Python `csv.DictReader` 计数和合并。

修复后：

- 每个节点仍为 6,250 个唯一 candidate ID；
- 全局为 50,000 个唯一 ID；
- 无重复；
- 8 个节点归档 SHA256 均通过；
- 聚合阶段重新校验了 49,840 个成功 PDB 的文件大小、SHA256、序列一致性和 atom 数；
- 最终无残留 `.partial` 文件。

## 4. TNP 部署方式与验证

上游代码：

```text
https://github.com/oxpig/TNP
commit 29dcac72f1380e8538e8870f45a699d3c6156162
```

官方 CLI 当前只开放 sequence/FASTA 输入，会再次调用 NanoBodyBuilder2；此外它与 bxcpu 当前新版 ANARCI API 不兼容。因此本轮没有重复建模，而是：

```text
冻结的 ANARCI/IMGT CDR 字段
+ 已有 NanoBodyBuilder2 IMGT-numbered PDB
-> 官方 TNP compactness 函数
-> 官方 TNP PSH/PPC/PNC 函数与 psa 二进制
```

适配器：

```text
pvrig_500k_generation_20260721/scripts/tnp_score_precomputed_pdb.py
```

验证证据：

1. 单条真实候选：PASS；
2. 64 条并行 smoke：64/64 PASS，约 4.06 秒；
3. 对 TNP 仓库自带 Enristomig VHH1 PDB 做上游参考数值复现：在预设容差内通过；
4. 全量 50k：49,840 PASS，160 个缺结构技术 NA；ID 集合与 selection 精确一致。

部署收据：

```text
pvrig_500k_generation_20260721/run/pvrig_bxcpu_tnp_deployment_v1_20260722/DEPLOYMENT_RECEIPT.json
```

## 5. TNP 结果概况

对 49,840 条有结构候选：

| 指标 | 5% 分位 | 中位数 | 95% 分位 |
|---|---:|---:|---:|
| CDR3 compactness | 0.8930 | 1.3784 | 1.5261 |
| PSH | 79.7960 | 101.1330 | 130.6881 |
| PPC | 0.0000 | 0.1772 | 1.6449 |
| PNC | 0.0000 | 0.1207 | 1.6388 |

TNP red flag 数量分布：

| red flag 数 | 候选数 |
|---:|---:|
| 0 | 39,837 |
| 1 | 9,494 |
| 2 | 506 |
| 3 | 3 |
| NA | 160 |

这些值适合作为可开发性/表达纯度风险代理和多目标排序列，不是实验表达量或纯度测量值。

## 6. 结果路径

### 本地统一 50k release

```text
/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_prestructure50k_multimetric_v1_20260722/
```

核心文件：

```text
prestructure50000_multimetric.tsv.gz
METRIC_SUMMARY.json
READY.json
SHA256SUMS
```

统一表 SHA256：

```text
ea4cffbbec119a092487d4c9d7ba5a254a0b236cc050f19d0ef3a45a9b3c9c45
```

### 本地 NBB2 结构归档

```text
/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_prestructure50k_nbb2_bxcpu_v1_20260722/
```

- `node_000.tar.gz` 至 `node_007.tar.gz` 已全部下载；
- 8/8 本地 SHA256 已通过；
- `LOCAL_TRANSFER_COMPLETE` 已生成。

### 本地 TNP 聚合

```text
/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_prestructure50k_tnp_bxcpu_v1_20260722/tnp_aggregate/
```

### bxcpu 副本

```text
$HOME/pvrig_bxcpu_model_runtime_v1_20260721/prestructure50k_v1/
```

## 7. Node1 同步状态

本地和 bxcpu 结果已经完成。当前 `node1` 主机名/SSH 仍不稳定，因此不能宣称 Node1 已同步完成。

以下自动重试任务仍在运行：

```text
pvrig_nbb2_50k_sync_20260722
pvrig_nbb2_then_tnp_20260722
pvrig_multimetric_node1_sync_20260722
```

只有在 Node1 端重新执行 `sha256sum -c SHA256SUMS` 成功后，脚本才会写入 `NODE1_SYNC_COMPLETE`。

## 8. 科学解释边界

- NanoBodyBuilder2：单体结构几何预测，不是结合、亲和力、Docking 或阻断证据；
- TNP：结构可开发性风险代理，不是实测表达量或纯度；
- DeepNano/NanoBind：weak binding prior，不是 Kd、IC50 或阻断结果；
- 本轮 50k 是 provisional reusable structure pool，不是最终 Docking surrogate top-50k；
- 160 个技术 NA 必须保持 NA，不能当作负样本。
