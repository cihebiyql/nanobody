# node1 PVRIG 比赛 VHH QC 门控 Runbook

更新时间：2026-07-19  
本地目录：`/mnt/d/work/抗体/node1`  
远端工具目录：`/data/qlyu/software/vhh_eval_tools`  
统一入口：`/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc`

大规模 cascade 入口：`/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen`

大规模运行、断点续跑、容量估算和最终 blocker 标签见：

```text
VHH_LARGE_SCALE_SCREENING_RUNBOOK.md
```

2026-07-11 的优化不改变 `vhh-competition-qc` 默认 `competition` 策略。新入口只在大规模 fast 层启用去重、官方 CLI 延后、LCS 精确 novelty 剪枝、昂贵指标后移和 geometry shortlist；full shortlist 仍重跑官方 validator，最终高置信阳性仍要求 `CONSENSUS_BLOCKER_LIKE_A`。

## 1. 当前状态

已把上一版方案推进为可执行 pipeline，并在 node1 跑通以下门控：

| 门控 | 状态 | 证据 |
| --- | --- | --- |
| 官方提交合规 | 已跑通 | `ab-data-validator` 已部署，smoke 输出 `official_failed_reasons.csv` |
| ANARCI/IMGT 编号和 CDR 完整性 | 已跑通 | `vhh-screen` L1，坏序列被硬拒 |
| CDR 阳参新颖性 `<80%` | 已跑通 | `cdr_novelty.tsv`，PVRIG-20 阳性被识别为 `max_CDR_identity_to_positive=1.0` |
| 队内重复/多样性 | 已跑通 | `team_diversity.tsv`，输出 `intra_team_cluster_id` 和 `max_team_identity` |
| VHH framework / AbNatiV | 已跑通 | `vhh-screen` L2，非 VHH/poor 会硬拒或降级 |
| PTM/liability/developability | 已跑通 | `vhh-screen` L3 + `developability_score` |
| 表达/纯度代理分 | 已跑通 | `expression_purity_risk_score` |
| 结构合理性 | 已跑通 | 结构 smoke 生成 `nanobodybuilder2.pdb`，`structure_quality_flag=PASS` |
| docking/blocking 回填 | 已跑通 | PVRIG-20 calibration summary 导入后 `blocker_class=SINGLE_BASELINE_BLOCKER_RECHECK` |
| Top N / reserve portfolio 输出 | 已跑通 | `portfolio_ranked.tsv`、`submission_top*.fasta/.xlsx`、`reserve_*.fasta` |

说明：HADDOCK3 全量 docking 仍是单独的重计算流程；本入口负责读取其 summary 并统一回填到提交筛选表。新候选需要先用 `docking/success_case_validation/prepare_candidate_sequence_workflow.py` 和 HADDOCK3 跑出 summary，再作为 `--docking-summary` 输入。

## 2. 新增/固定的远端入口

```bash
/data/qlyu/software/vhh_eval_tools/bin/ab-data-validator
/data/qlyu/software/vhh_eval_tools/bin/muscle
/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc
/data/qlyu/software/vhh_eval_tools/competition_qc/vhh_competition_qc.py
/data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv
/data/qlyu/software/vhh_eval_tools/references/official_positive_library_cdrs.csv
```

`ab-data-validator` 源码部署在：

```bash
/data/qlyu/software/ab-data-validator
```

`muscle` 版本：

```text
muscle 5.3.linux64
```

`vhh-competition-qc` 每次运行还会输出阶段耗时：

```text
stage_timings.tsv
```

官方阳参 CDR 表默认缓存到：

```text
/data/qlyu/software/vhh_eval_tools/references/official_positive_library_cdrs.csv
```

如需重建缓存：

```bash
--refresh-positive-cdr-cache
```

## 3. 快速调用

### 3.1 序列层级完整 QC，不跑结构

适合大批量候选初筛：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
OUT=$ROOT/runs/my_competition_qc_$(date +%Y%m%d_%H%M%S)
$ROOT/bin/vhh-competition-qc candidates.fasta \
  -o $OUT \
  --prefix my_batch \
  --workers 8 \
  --tnp-ncores 4 \
  --local-positive-cdr-csv $ROOT/references/local_pvrig_positive_vhh_cdrs.csv \
  --top-n 50 \
  --reserve-n 20
'
```

### 3.2 Top hits 结构版 QC

适合 Top 50-100 的复核：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
OUT=$ROOT/runs/my_competition_qc_struct_$(date +%Y%m%d_%H%M%S)
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/vhh-competition-qc top_hits.fasta \
  -o $OUT \
  --prefix top_hits \
  --workers 8 \
  --tnp-ncores 1 \
  --structure-tools nanobodybuilder2 \
  --max-structures 50 \
  --gpu 0 \
  --local-positive-cdr-csv $ROOT/references/local_pvrig_positive_vhh_cdrs.csv \
  --top-n 50 \
  --reserve-n 20
'
```

### 3.3 带 HADDOCK/blocking summary 的最终排序

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
OUT=$ROOT/runs/my_competition_qc_final_$(date +%Y%m%d_%H%M%S)
$ROOT/bin/vhh-competition-qc top_hits.fasta \
  -o $OUT \
  --prefix final \
  --workers 8 \
  --tnp-ncores 1 \
  --local-positive-cdr-csv $ROOT/references/local_pvrig_positive_vhh_cdrs.csv \
  --docking-summary /path/to/haddock_or_consensus_summary.csv \
  --top-n 50 \
  --reserve-n 20
'
```

`--docking-summary` 支持这些常见列名：

```text
candidate_id / id / name / fasta_id / molecule_name
blocker_class / class / top_model_consensus_class
hotspot_overlap_count / top_8x6b_hotspot
total_vhh_pvrl2_residue_pair_occlusion / top_8x6b_total_occlusion
```

## 4. 输出文件

每次运行主要输出：

```text
<prefix>.normalized.fasta
<prefix>.official_submit.xlsx
official_failed_reasons.csv
official_validator.log
vhh_screen/screen_summary.tsv
vhh_screen/<prefix>.vhh_eval.tsv
cdr_novelty.tsv
team_diversity.tsv
portfolio_ranked.tsv
submission_top<N>.fasta
submission_top<N>.xlsx
reserve_<N>.fasta
portfolio_report.md
competition_qc_details.json
```

重点看 `portfolio_ranked.tsv`，其中包括：

```text
official_validator_pass
pass_similarity_filter
max_CDR_identity_to_positive
intra_team_cluster_id
AbNatiV_VHH_score
AbNatiV_FR_VHH_score
Sapiens_mean_self_probability
Sapiens_num_suggested_mutations
developability_score
expression_purity_risk_score
structure_score
binding_score
PVRL2_competition_score
blocker_class
final_score
recommendation
reason_summary
```

## 5. 已完成 smoke evidence

### 5.1 快速 smoke：官方合规 + novelty + developability + portfolio

输出目录：

```text
/data/qlyu/software/vhh_eval_tools/tests/competition_qc_smoke_20260708_135324
```

结果：

```text
Candidates: 3
Official validator failures: 2
Hard gate rejects: 2
Selected Top 2: 1
vhh_smoke -> REVIEW_DEVELOPABILITY
official_positive_20 -> REJECT_HARD_GATE
bad_non_antibody -> REJECT_HARD_GATE
```

### 5.2 结构 smoke：NanoBodyBuilder2 L4 gate

输出目录：

```text
/data/qlyu/software/vhh_eval_tools/tests/competition_qc_struct_smoke_20260708_135623
```

结构证据：

```text
/data/qlyu/software/vhh_eval_tools/tests/competition_qc_struct_smoke_20260708_135623/vhh_screen/structures/vhh_smoke/nanobodybuilder2.pdb
```

关键结果：

```text
vhh_smoke structure_quality_flag=PASS
vhh_smoke structure_score=100.00
vhh_smoke final_score=70.63
```

### 5.3 docking/blocking import smoke

输出目录：

```text
/data/qlyu/software/vhh_eval_tools/tests/competition_qc_docking_import_20260708_135938
```

输入使用 PVRIG-20 calibration summary，关键结果：

```text
candidate_id=PVRIG-20
binding_score=80.00
PVRL2_competition_score=75.00
blocker_class=SINGLE_BASELINE_BLOCKER_RECHECK
```

### 5.4 blocker workflow regression

本地运行：

```bash
cd /mnt/d/work/抗体
python3 docking/success_case_validation/test_success_case_workflow.py
```

结果：

```text
OK success-case workflow regression test passed
```

### 5.5 sub agent 速度复查

复查目录：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_competition_qc_20260708_141101
/data/qlyu/software/vhh_eval_tools/tests/competition_qc_speed_main_20260708_140912
/data/qlyu/software/vhh_eval_tools/tests/competition_qc_speed_cached_20260708_142211
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_20260708_145542
```

实测结论：

```text
help: 约 0.6-1.1 s
1 条有效 VHH，完整无结构序列门控：约 96-116 s
3-4 条候选，完整无结构序列门控：约 111-139 s
1 条有效 VHH + NanoBodyBuilder2 --max-structures 1：约 150 s
```

缓存后 1 条候选的阶段级耗时示例：

```text
official_validator          10.910 s
vhh_screen                  82.057 s
load_official_positive_cdrs 0.004 s
positive_cdr_novelty        2.860 s
```

当前主要瓶颈：

```text
1. vhh-screen 子流程：AbNatiV / Sapiens / TNP / 模型加载，总体约 80 s/小批次。
2. official validator：仍要做官方 hard gate；缓存只加速本入口自己的 novelty CDR 读取，不改变官方 validator 的保守检查语义。
3. 不要逐条单独跑；应把 50 条候选合并成一个 FASTA 批量跑，摊薄固定启动成本。
```

复查边界：

```text
当前 smoke 证明小规模门控连通，不证明全量 Top50 和 HADDOCK 新候选端到端稳定。
新候选 HADDOCK3 docking / occlusion / consensus 仍需先用 success_case_validation workflow 单独跑，再通过 --docking-summary 导入。
```

### 5.6 50 条真实 scaffold 批量 benchmark

输入来源：

```text
/mnt/d/work/抗体/scaffolds/top_200_vhh_scaffolds_for_design.fasta
```

测试输入：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds.fasta
```

输出目录：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_20260708_145542/qc
```

总耗时：

```text
real 1559.37 s
约 26.0 min
```

阶段耗时：

```text
official_validator     82.929 s
vhh_screen           1304.451 s
positive_cdr_novelty  121.274 s
team_diversity         48.221 s
```

结果统计：

```text
Candidates: 50
Official validator failures: 8
Hard gate rejects: 32
Eligible / selected: 18
Recommendation counts:
  REJECT_HARD_GATE: 32
  REVIEW_DEVELOPABILITY: 12
  REVIEW_RISK: 6
official_validator_pass:
  PASS: 42
  FAIL: 8
pass_similarity_filter:
  PASS: 46
  FAIL: 4
blocker_class:
  NOT_RUN: 50
```

解释：

```text
本次是非结构、非 HADDOCK 的 50 条批量门控，用于测试官方合规、vhh-screen L1-L3、CDR novelty、队内 diversity 和 portfolio 输出。
没有运行 NanoBodyBuilder2 结构、Chai/Boltz/HADDOCK 或 blocking occlusion；因此 blocker_class=NOT_RUN 是预期。
```

### 5.7 18 条 eligible scaffold 结构层 benchmark

输入来自 5.6 的 50 条批筛结果，只抽取 `hard_fail=False` 的 18 条：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_eligible18.fasta
```

输出目录：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_eligible18_struct_20260708_165506/qc
```

运行命令要点：

```bash
CUDA_VISIBLE_DEVICES=0 /data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc \
  /data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_eligible18.fasta \
  -o /data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_eligible18_struct_20260708_165506/qc \
  --prefix top50_eligible18_struct \
  --workers 8 \
  --tnp-ncores 1 \
  --structure-tools nanobodybuilder2 \
  --max-structures 18 \
  --gpu 0 \
  --local-positive-cdr-csv /data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv \
  --top-n 18 \
  --reserve-n 0
```

总耗时：

```text
real 658.58 s
约 11.0 min
```

阶段耗时：

```text
official_validator      32.828 s
vhh_screen             576.862 s
positive_cdr_novelty    42.659 s
team_diversity           5.859 s
```

结果统计：

```text
Candidates: 18
Official validator failures: 0
Hard gate rejects: 0
Selected Top 18: 18
Recommendation counts:
  REVIEW_DEVELOPABILITY: 12
  REVIEW_RISK: 6
L1_numbering_integrity:
  PASS: 18
L2_vhh_features:
  PASS: 18
L3_developability:
  WARN: 13
  FAIL: 5
L4_structure_stability:
  PASS: 13
  SKIPPED: 5
blocker_class:
  NOT_RUN: 18
```

解释：

```text
13 条生成 NanoBodyBuilder2 PDB 且 L4=PASS。
5 条没有结构 PDB，不是结构建模报错；原因是 L3_developability=FAIL 后按规则跳过结构，L4_reasons=INFO:skipped_after_L3_fail。
本次仍未运行 Chai/Boltz/HADDOCK 或 PVRL2 occlusion；blocker_class=NOT_RUN 是预期。
```

后续 docking/复合物建模输入已单独抽出：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_l4pass13_for_docking.fasta
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_l4pass13_for_docking.tsv
```

风险复核表：

```text
/data/qlyu/software/vhh_eval_tools/tests/benchmark_top50_scaffolds_l3fail5_risk.tsv
```

说明：风险表实际含 6 条，其中 5 条是 `L3_developability=FAIL` 后结构跳过，另 1 条结构 PASS 但 developability score 低于 65。

## 6. 判定规则摘要

硬拒：

```text
official_validator_pass=FAIL
L1_numbering_integrity=FAIL
L2_vhh_features=FAIL 或 single_domain_suitability=poor
pass_similarity_filter=FAIL
invalid amino acids
odd cysteine count
hydrophobic 5-run
L4_structure_stability=FAIL
```

评分：

```text
final_score =
  0.20 * binding_score
+ 0.20 * blocking_score
+ 0.20 * developability_score
+ 0.15 * expression_purity_risk_score
+ 0.10 * structure_score
+ 0.10 * novelty_score
+ 0.05 * diversity_score
```

注意：未跑结构或 docking 时，对应分数保持中性，避免在早期批筛误杀；正式 Top 50 前建议对 Top hits 补结构和 docking/blocking summary。

## 7. 维护边界

- `ab-data-validator` 是官方 hard gate，后续若官方仓库/附件更新，应重新同步源码或 Docker 版本。
- TNP/AbNatiV/NanoBodyBuilder2 等是内部风险分，不是官方淘汰线。
- `BLOCKER_LIKE_A` / `SINGLE_BASELINE_BLOCKER_RECHECK` 是结构假设，不是实验 IC50/Kd。
- 大批量跑结构和 HADDOCK 前先查 GPU：`nvidia-smi`。
