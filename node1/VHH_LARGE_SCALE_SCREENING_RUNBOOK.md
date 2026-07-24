# PVRIG VHH 大规模最终阳性筛选 Runbook

> 2026-07-24 指标升级：生产排名、缺失值、多 seed/双构象共识和
> 表达/纯度拆分见
> `PVRIG_VHH_PRODUCTION_SCREENING_METRICS_PLAN_20260724.md`。

更新时间：2026-07-19

## 一句话结论

可以大规模筛选，但必须使用分层漏斗，而不是对全库运行 TNP、team diversity、结构和 docking。

新的生产入口：

```text
/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen
```

默认策略：

```text
全库：去重 + 基础 hard gate + L1 + official/local positive CDR novelty
  -> shortlist：官方 validator + AbNatiV + Sapiens，默认不跑 TNP
  -> geometry pool：全局精确 team diversity
  -> geometry shortlist：结构预测 + HADDOCK3 + 8X6B/9E6Y consensus
  -> FINAL_POSITIVE_HIGH：只接受导入的 CONSENSUS_BLOCKER_LIKE_A
```

## 为什么这样更稳

1. `vhh-competition-qc` 默认 `competition` 行为保持不变；旧命令仍按原 hard gate 运行。
2. 大规模 fast 层使用 `blocker_calibrated`：FR2/VHH-like、hydrophobic-run、TNP 风险只进入 review，不提前淘汰潜在 blocker。
3. official CLI 在 fast 层延后，但 official positive CDR cache novelty 仍运行；full shortlist 必须重新运行官方 CLI。
4. positive novelty 仍以 MUSCLE identity 为最终值；新增 LCS 理论上界只剪掉不可能超过当前最优的 pair。
5. team diversity 不在全库做 O(N^2)，只在有界 geometry pool 上全局精确计算。
6. sequence-only / DeepNano / AbNatiV / Sapiens 都不能产生最终 blocker 阳性；最终高置信阳性必须有双 baseline docking consensus。

## 推荐命令

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
IN=/data/qlyu/projects/my_candidates/candidates.fasta
OUT=$ROOT/runs/my_large_scale_screen_$(date +%Y%m%d_%H%M%S)

$ROOT/bin/vhh-large-scale-screen "$IN" -o "$OUT" \
  --fast-chunk-size 500 \
  --chunk-jobs 2 \
  --full-qc-limit 1000 \
  --full-chunk-size 100 \
  --full-chunk-jobs 1 \
  --geometry-pool-size 100 \
  --geometry-limit 50 \
  --geometry-cluster-limit 3 \
  --workers 16 \
  --tnp-ncores 4 \
  --identity-cache-size 500000 \
  --local-positive-cdr-csv \
    $ROOT/references/local_pvrig_positive_vhh_cdrs.csv
'
```

如果已有 DeepNano 或其他 binder 预筛表，可加入：

```text
--binder-summary /path/to/binder_scores.csv
```

支持的候选 ID 列包括 `candidate_id/nanobody_id/id/name/fasta_id/molecule_name`。新版优先读取 `binding_prior_consensus`，同时仍兼容 `binder_score/DeepNano_score/deepnano_score/binding_score/score`。

### Node1 已跑通的 binding-prior 前筛

生产入口：

```text
/data1/qlyu/software/vhh_eval_tools/bin/vhh-binding-prior
```

它并行运行 DeepNano 8M model 1 和 NanoBind-seq，然后生成可直接交给 `--binder-summary` 的表。`NanoBind-affi` 默认不运行；只在 `RUN_AFFINITY=1` 时追加通用参考集锚定的 affinity range。

```bash
ssh.exe node1 '
ROOT=/data1/qlyu/software/vhh_eval_tools
CASCADE=/data1/qlyu/projects/my_run/cascade
PRIOR=/data1/qlyu/projects/my_run/binding_prior
PVRIG=/data1/qlyu/projects/my_run/pvrig_ecd.fasta

# 1. 先去重并执行最便宜的长度/字符 hard gate
$ROOT/bin/vhh-large-scale-screen candidates.fasta -o "$CASCADE" --stage prepare

# 2. 对 unique_candidates 生成结合先验；默认不跑 affinity range
DEEPNANO_GPU=1 NANOBIND_GPU=2 \
  $ROOT/bin/vhh-binding-prior \
  "$CASCADE/unique_candidates.fasta" "$PVRIG" "$PRIOR"

# 3. 在 fast/full merge 时用 prior 排序，不改变 hard gate
$ROOT/bin/vhh-large-scale-screen candidates.fasta -o "$CASCADE" --stage fast \
  --binder-summary "$PRIOR/binding_prior_table.tsv"
'
```

独立输出列：

```text
deepnano_binding_prior
nabp_binding_prior
nanobind_binding_prior
nanobind_affinity_range
binding_model_count
binding_prior_consensus
binding_model_disagreement
binding_prior_status
binding_prior_source
```

2026-07-19 的 10 条 Node1 E2E smoke：DeepNano 8M `7.31 s`，NanoBind-seq `7.52 s`，NanoBind-affi `18.73 s`；前两者并行。HR-151/PVRIG 上 DeepNano 和 NanoBind 分别给出 `0.1024` 和 `0.5487`，被正确标为 `MULTI_MODEL_DISAGREEMENT`，这也说明不能将任一单模型作为 hard fail。

## docking 完成后的最终归类

第一次 `all` 运行没有 docking summary 时，geometry shortlist 会被标为：

```text
FINAL_INCOMPLETE_NEEDS_DOCKING
```

完成结构和 HADDOCK3 后，复用同一输出目录：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-large-scale-screen /path/to/original_candidates.fasta \
  -o /path/to/existing_cascade_out \
  --stage finalize \
  --docking-summary /path/to/docking_consensus.csv
'
```

最终标签：

| 标签 | 解释 |
| --- | --- |
| `FINAL_POSITIVE_HIGH` | 已导入 `CONSENSUS_BLOCKER_LIKE_A`；当前最高计算优先级 |
| `FINAL_RECHECK_SINGLE_BASELINE` | 只有单 baseline A 或非 consensus A，必须重跑/人工看 pose |
| `FINAL_POSITIVE_PLAUSIBLE` | `BLOCKER_PLAUSIBLE_B`，可保留但低于 A/A |
| `FINAL_BINDER_NOT_BLOCKER` | binder-like，不支持 PVRL2 阻断 |
| `FINAL_INSUFFICIENT_GEOMETRY` | 几何证据不足 |
| `FINAL_INCOMPLETE_NEEDS_DOCKING` | 尚未导入 docking evidence |

## 关键输出

```text
cascade_manifest.json
cascade_state.json
input_map.tsv
quick_rejects.tsv
unique_candidates.fasta
fast_chunk_status.tsv
fast_merged.tsv
full_qc_shortlist.tsv
full_qc_excluded_due_cap.tsv
full_chunk_status.tsv
full_merged.tsv
geometry_shortlist.tsv
geometry_shortlist.fasta
geometry_diversity_excluded.tsv
final_blocker_screen.tsv
final_positive_high.fasta
CASCADE_RUN_REPORT.md
```

重要：`full_qc_excluded_due_cap.tsv` 表示“容量延后”，不是生物学阴性。若不能接受容量截断，设置：

```text
--full-qc-limit 0
```

## TNP 策略

默认 full shortlist 不跑 TNP，因为：

- TNP 是可开发性风险指标，不是 PVRIG-PVRL2 blocker hard gate。
- 现有阳性中有 2/11 TNP PNC red，不能据此淘汰 blocker。
- 10 条 shortlist 实测：带 TNP 462.48 秒，不带 TNP 143.38 秒。

若确实要求 full shortlist 全部补 TNP：

```text
--full-run-tnp
```

更推荐只对 geometry shortlist、最终 high/plausible 或准备实验的候选补 TNP。

## 实测性能

证据表：`competition_qc/large_scale_benchmark_20260711.csv`

| 模式 | 实测 |
| --- | ---: |
| 旧 full QC 50 条 | 1559.37 s（25.99 min） |
| 新 fast 50 条 | 24.98 s |
| 新 cascade 50 -> full 10 -> geometry 5 | 169.82 s（2.83 min，不含 docking） |
| 完成后 resume | 1.15 s |
| novelty LCS 剪枝关闭 | 13.577 s |
| novelty LCS 精确剪枝 | 0.349 s |

novelty A/B 验证：

- `cdr_novelty.tsv` 字节级一致。
- identity requests：908 -> 33。
- MUSCLE cache misses：653 -> 22。
- novelty 阶段约 39 倍加速。
- 50 条真实 scaffold 与旧 full run 对比：L1/基础字段差异 0，CDR identity/pass/borderline 字段差异 0。

50 条真实 scaffold cascade 输出约 1.7 MB，其中 fast chunks 约 1.2 MB。粗略外推 100,000 条 fast 中间文件约 2-3 GB，应按独立 run 目录并定期归档。

## 容量估算

按当前 node1 50 条 fast 基准约 2 条/秒：

| 输入规模 | fast 层粗估 | 后续建议 |
| ---: | ---: | --- |
| 1,000 | 8-15 min | full 100-300；geometry 20-50 |
| 10,000 | 1.5-2.5 h | 有 binder summary 时 full 500-1000 |
| 100,000 | 12-18 h | 分 chunk、断点续跑；full 固定上限，不能全量 docking |

这些是容量规划，不是 SLA；node1 并发负载、ANARCI/MUSCLE 进程数、磁盘和输入序列质量都会影响时间。

## 稳定运行规则

- 每个 chunk 只有在 `portfolio_ranked.tsv` 行数与输入一致时才写 `complete.json`。
- 重跑默认复用完成 chunk；50 条 cascade 实测 resume 1.15 秒，生产 smoke 为 0.91 秒。
- 输入或关键配置变化时 manifest digest 不一致会拒绝复用；使用新输出目录最安全。
- `--force` 只用于明确重建当前 cascade 目录。
- positive controls 和 mutant controls 保持独立 calibration lane，不混入新候选提交。
- `FINAL_RECHECK_SINGLE_BASELINE` 不得自动升级为高置信阳性。
- docking label 是计算优先级，不替代 Kd、IC50 或细胞阻断实验。

## 部署与回滚

生产文件：

```text
/data/qlyu/software/vhh_eval_tools/competition_qc/vhh_competition_qc.py
/data/qlyu/software/vhh_eval_tools/competition_qc/vhh_large_scale_screen.py
/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen
```

升级前 core 备份：

```text
/data/qlyu/software/vhh_eval_tools/competition_qc/vhh_competition_qc.py.bak.20260711_optimization
```

默认 `vhh-competition-qc` 部署后 smoke 仍为：3 条输入、2 条 hard reject、1 条 `REVIEW_DEVELOPABILITY`。
