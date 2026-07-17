# PVRIG V4-H 当前成功 Docking 的全链路 Partial Preview

日期：2026-07-17

## 1. 目的与边界

按用户明确要求，本轮从仍在运行的 Node23 V4-H campaign 中提取“快照时已经成功”的 Docking jobs，测试：

```text
Node23 SUCCESS job_result
→ 冻结 scorer
→ 双受体 partial R_dual_min
→ 本地拉取和哈希闭合
→ M1 sequence-only / M2 structure-only 评估
```

这是主动运行 campaign 的 **partial development preview**，不是 terminal teacher。它存在 job 顺序、完成速度和技术成功选择偏差，不能称为 Docking Gold、实验结合或阻断证据。

## 2. 数据拉取方式

快照开始时，Node23 的成功 `job_result.json` 总量约 11.6 GiB，因此没有拉取全部原始 JSON。聚合在 Node23 端完成，只拉回：

- 逐 job status/result SHA256 和冻结 score；
- 1320 条 candidate partial teacher；
- immutable snapshot receipt。

V1 首次执行发现：`status=SUCCESS` 不保证冻结 scorer 可接受。至少一条结果因 `native_overlay_rmsd_above_1A` 失败，因此 V1 fail-closed，没有发布 teacher。

V1.1 未修改 RMSD 阈值，而是把这类 job 记录为：

```text
SCORING_INVALID
partial_score = 空
```

然后继续处理其余 job。

## 3. 快照规模

快照 V1.1：

| 项目 | 数量 |
|---|---:|
| status-SUCCESS jobs captured | 1,923 |
| frozen scorer valid jobs | 1,901 |
| SCORING_INVALID jobs | 22 |
| PARTIAL_ANALYZABLE candidates | 937 |
| PARTIAL_INCOMPLETE candidates | 383 |
| 总候选 | 1,320 |

22 个 scorer invalid 全部为冻结的 native-overlay RMSD 门失败，没有放宽阈值，也没有填补分数。

快照文件：

```text
prepared/pvrig_v4_h_partial_success_snapshot_v1_1_20260717T114514Z/
  partial_candidate_teacher_snapshot_v1_1.tsv
  successful_jobs_snapshot_v1_1.tsv
  partial_success_snapshot_v1_1.receipt.json
```

关键 SHA256：

```text
partial teacher : d11b3ce15a4a53f9d426cfb2451716fb26b7b2bf1f886b584153a9985082ae1e
job provenance  : 99d503f0bcd888cffe07b4cb00cfabdf0a12767fe38eab8fcf6626bcd0fa702c
snapshot receipt: 25aea48edbc35af0c2f99d1d83441493ddb2184d33fdd9f48653f722d6c894f7
```

## 4. Partial preview 结果

937 条当前双受体可分析候选：

| 模型 | Spearman | Pearson | MAE | NDCG | Top20% recall |
|---|---:|---:|---:|---:|---:|
| M1 sequence-only | 0.5240 | 0.4947 | 0.03444 | 0.98403 | 0.3989 |
| **M2 structure-only** | **0.5667** | **0.5310** | **0.03365** | **0.98443** | **0.4574** |

M2 − M1 的 paired parent-group bootstrap：

```text
median ΔSpearman = +0.04138
95% CI           = [+0.01419, +0.09730]
Δ > 0 fraction   = 0.9994
```

parent-centered Spearman：

| 模型 | parent-centered Spearman |
|---|---:|
| M1 sequence-only | 0.1389 |
| M2 structure-only | 0.1977 |

10 个当前有足够行的 parent 的 macro Spearman：

| 模型 | macro mean | macro median |
|---|---:|---:|
| M1 | 0.1157 | 0.1151 |
| M2 | 0.1995 | 0.1848 |

因此 partial preview 支持：

1. 使用 VHH 单体结构特征确实比纯序列表征更接近当前 Docking 几何；
2. 改善不只来自全局 parent 差异，parent-centered 和 per-parent macro 也提高；
3. 但 within-parent 信号仍然偏弱，M2 parent-centered 只有约 0.20，不能代替真实 Docking。

## 5. 当前最重要的偏差

这 937 条不是随机样本，parent coverage 极不均衡：

| parent | analyzable / 120 |
|---|---:|
| C0078 | 118 |
| C0086 | 116 |
| C0145 | 117 |
| C0148 | 115 |
| C0162 | 112 |
| C0176 | 0 |
| C0283 | 29 |
| C0348 | 38 |
| C0360 | 77 |
| C0409 | 96 |
| C0417 | 119 |

尤其 `C0176=0`、`C0283=29`，说明当前 global 指标明显受 controller/job 顺序影响。patch 和 mode coverage 相对均衡：

```text
A_CENTER 312 / 440
B_LOWER  306 / 440
C_CROSS  319 / 440

H1H3 461 / 660
H3   476 / 660
```

所以不能用本轮结果修改模型、阈值或挑选 parent。

## 6. 结论和下一步

当前最合理的结论是：

> M2 structure-only 是目前更好的 Docking 几何代理；在强选择偏差的 937 条 partial 数据上，它相对 M1 的优势在多个指标上方向一致。但模型的同-parent 排序能力仍有限，必须等待 1320 条 terminal teacher 和后续多 seed 结果确认。

继续执行：

1. Node23 原 campaign 不做改动，继续完成 stage1/2/3；
2. 不修改 M1/M2、结构特征、RMSD 门或 terminal evaluator；
3. terminal receipt 出现后，使用已冻结 adapter 生成唯一 terminal teacher；
4. 在全 1320 和更完整 seed 数据上重新运行相同指标；
5. 若 M2 的 terminal parent-centered Spearman 仍稳定优于 M1，再将 M2 用于大库结构前筛，同时施加 parent portfolio 限制。

评估输出：

```text
reports/pvrig_v4_h_partial_success_preview_v1_1_20260717T114514Z/
```

geometry access disclosure：

```text
audits/phase2_v4_h_partial_geometry_access_disclosure_v1_20260717.json
SHA256 cb44c23623323c6845b5057e5c17b178e8a7f2e46903d89b4cf70b7efa309e2f
```
