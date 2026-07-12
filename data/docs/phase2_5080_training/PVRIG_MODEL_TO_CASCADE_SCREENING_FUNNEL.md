# PVRIG 候选筛选漏斗：模型前筛到实验真值

## 目标与边界

这条链路把已有模型和 Node1 `vhh-large-scale-screen` 组合成一个分层漏斗：

```text
大规模 VHH 序列库
  -> 模型前筛（廉价、全量、相对优先级）
  -> cascade fast/full QC（严格序列、novelty、可开发性与多样性）
  -> geometry shortlist
  -> 8X6B + 9E6Y 结构/HADDOCK3 双基线共识
  -> 表达/SEC -> BLI/SPR -> competition -> functional
  -> 人工复核的新证据 -> 新 V2.6 split/seal/formal protocol
```

四层责任不能混淆：

1. 模型只负责全库前期大规模排序。
2. cascade 负责 shortlist 严格 QC、可开发性审查和计算排序。
3. docking consensus 负责是否具有 PVRIG-PVRL2 阻断样几何的计算证据。
4. 只有真实实验和人工科学复核才能产生新的 binding/blocking/functional 证据。

## 阶段 A：模型全库前筛

模型输出先通过本地适配器转换：

```bash
EXP=experiments/phase2_5080_v1

python "$EXP/src/prepare_pvrig_model_screening_summary.py" \
  --input "$EXP/predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv" \
  --output "$EXP/predictions/pvrig_model_frontscreen_summary_v1.csv" \
  --id-column candidate_id \
  --score-column phase2_v2_4_sequence_ensemble_score
```

输出中 cascade 使用的字段名是 `binder_score`，但它的真实语义是：

```text
within_input_rank_percentile_higher_is_better
```

它不是 binding probability，也不是 blocker probability。输入集合改变后，同一序列的 percentile 可以改变，因此不应在不同候选库之间当作绝对标尺。

如果必须保持盲法 ID，使用映射参数：

```bash
python "$EXP/src/prepare_pvrig_model_screening_summary.py" \
  --input "$EXP/predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv" \
  --output "$EXP/assays/pvrig_v2_5_prospective_v1/model_frontscreen_summary_blinded.csv" \
  --id-map "$EXP/assays/pvrig_v2_5_prospective_v1/blinding_key.csv" \
  --map-source-column candidate_id \
  --map-target-column assay_sample_id
```

这个文件只保留能在 ID map 中匹配到的候选。不得把
`blinding_key.csv` 提供给仪器操作者。

## 阶段 B：Node1 大规模 cascade

生产入口：

```text
/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen
```

建议调用：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
IN=/data/qlyu/projects/my_candidates/candidates.fasta
MODEL=/data/qlyu/projects/my_candidates/pvrig_model_frontscreen_summary_v1.csv
OUT=$ROOT/runs/my_large_scale_screen_$(date +%Y%m%d_%H%M%S)

$ROOT/bin/vhh-large-scale-screen "$IN" -o "$OUT" \
  --binder-summary "$MODEL" \
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
  --identity-cache-size 500000
'
```

`--binder-summary` 候选 ID 列依次支持
`candidate_id/id/name/fasta_id/molecule_name`，分数列依次支持
`binder_score/DeepNano_score/deepnano_score/binding_score/score`。本项目固定输出
`candidate_id` 和 `binder_score`，避免依赖回退推断。

如果不能接受容量截断，使用 `--full-qc-limit 0`。
`full_qc_excluded_due_cap.tsv` 表示容量延后，不是阴性。

cascade 的固定解释规则：

- fast/full hard reject 是序列或开发性筛选结果，不是 nonbinder 标签。
- official/local positive CDR novelty 是排除近重复的保护层，不证明新候选有阻断活性。
- blocker 模式下 FR2/VHH-like、疏水 run 和 TNP 红旗优先进 review，不轻率删除可能的 blocker。
- TNP 默认后移到最终 geometry/实验候选，不对全库执行。
- 全局精确 team diversity 只在有界 geometry pool 内计算，避免全库 O(N^2)。

断点复用受 input/config digest 约束。修改输入或关键参数后不能将旧 chunk 当作已完成；只有输出行数和输入一致的 chunk 才会写入 `complete.json`。

## 阶段 C：结构与双基线 docking

`geometry_shortlist.fasta` 是需要结构处理的有界队列。对每个候选：

1. 生成 VHH 单体并做 sequence/geometry QC。
2. 使用 8X6B PVRIG receptor setup 运行一次 HADDOCK3；不得把流程描述成对
   8X6B 和 9E6Y 各自独立 docking。
3. 将同一批 top poses 分别对齐并评分到 8X6B（PVRIG B/PVRL2 A）和
   9E6Y（PVRIG A/PVRL2 D）参考界面。
4. 在 Node1 负载低于固定 gate 时运行 HADDOCK3，不得绕过 load gate；若长期
   高负载，只能在本地同版本 runtime 通过 CNS 与真实全模块 smoke、并完成
   nonce 绑定的远端 waiter 所有权交接后切换执行端。
5. 对 top poses 做几何 QC 和 PVRIG-PVRL2 界面阻断样评分。
6. 生成 candidate-level docking summary，而不是直接传入 HADDOCK
   `traceback/consensus.tsv`。

当 Node1 长时间高负载时，可使用 geometry-4 包中的 guarded waiter。它通过
独立 tmux socket 持久运行，以 `flock` 防止重复实例，每 60 秒检查一次并在
24 小时后超时；每条候选启动前都必须满足严格的 `load1 < 64`，且不会删除
或覆盖不完整 run。当前实现还让直接 launcher 与 waiter 共享 per-candidate
lock，把 HUP/INT/TERM 记录为 `INTERRUPTED`，并在任何 SSH/tmux 调用前验证
数值参数：

```bash
bash docking/candidates/v2_5_geometry4_dual_baseline/scripts/deploy_guarded_haddock3_waiter_node1.sh --deploy
bash docking/candidates/v2_5_geometry4_dual_baseline/scripts/deploy_guarded_haddock3_waiter_node1.sh --status
```

docking summary 至少需要可识别的候选 ID（推荐
`candidate_id`）和可支持的 class 字段（推荐 `blocker_class`）。几何审计字段为：

```text
hotspot_overlap_count
total_vhh_pvrl2_residue_pair_occlusion
cdr3_pvrl2_residue_pair_occlusion
cdr3_occlusion_fraction
```

候选 ID 也支持 `id/name/fasta_id/molecule_name`，class 列也支持
`top_model_consensus_class/class`，但生产汇总应显式使用
`candidate_id` 和 `blocker_class`。

导入后只重跑 finalize：

```bash
vhh-large-scale-screen original_candidates.fasta \
  -o existing_cascade_output \
  --stage finalize \
  --docking-summary docking_consensus.csv
```

`--stage finalize` 要求同一输出目录已存在
`geometry_shortlist.tsv`。它只重读 geometry shortlist 和 docking summary，
不重算前面的 fast/full chunks。

不能把单个 8X6B 结果伪装成双基线 consensus。只有支持
`CONSENSUS_BLOCKER_LIKE_A` 的候选才能进入
`FINAL_POSITIVE_HIGH`；单基线 A 只能进入
`FINAL_RECHECK_SINGLE_BASELINE`。

geometry-4 汇总器还执行三项 fail-closed 保护：baseline 输入只接受明确的
`BLOCKER_LIKE_A`、`BLOCKER_PLAUSIBLE_B` 或 `BINDER_LIKE_C`（以及其单字母
等价值），不会把旧的 recheck 标签折叠成 A；完整候选必须从实际 VHH 输入
PDB 的 chain A 重建序列并与 manifest SHA256 一致；finalize CSV 只接收
`RUN`、双 baseline 且四个几何字段完整的记录。

## 阶段 D：finalize 计算标签

| 标签 | 用途 | 后续动作 |
| --- | --- | --- |
| `FINAL_POSITIVE_HIGH` | 双基线 A 类阻断样几何 | 优先实验，仍不是实验阳性 |
| `FINAL_RECHECK_SINGLE_BASELINE` | 单基线 A | 补另一 baseline 或人工审 pose |
| `FINAL_POSITIVE_PLAUSIBLE` | B 类阻断可能性 | 保留，优先级低于 A/A |
| `FINAL_BINDER_NOT_BLOCKER` | 计算上可能结合，但不支持阻断几何 | 可进入 binder/nonblocker 实验对照队列 |
| `FINAL_INSUFFICIENT_GEOMETRY` | 已有 evidence 类记录，但几何不足 | 补结构/对齐/基线证据并人工复核 |
| `FINAL_INCOMPLETE_NEEDS_DOCKING` | 没有可导入的 docking 证据 | 继续几何阶段，不得称阳性 |

上述仍然是计算标签，不得直接写入普通训练真值。

## 阶段 E：湿实验与新 V2.6 证据

当前 24 条 prospective panel 已经冻结，不因 cascade reject 或 geometry 排名而删除。模型与 cascade 不一致本身就是需要实验测量的 prospective evidence。

实验固定顺序：

1. expression/purification/SEC QC；
2. 全部 QC-pass 样本的 BLI/SPR binding；
3. 只对 verified binder 做 PVRIG-PVRL2 competition；
4. 只对 verified biochemical blocker 做 functional assay。

证据规则：

- expression 或 assay failure 不能变成 nonbinder。
- binding 不能自动升级为 blocker。
- 所有已填写的功能实验调用，包括 `INCONCLUSIVE`，都需要 analyte concentration、viability、raw path/SHA256 和独立运行证据。
- 完整的三次独立运行必须引用不同 raw-data 文件，且覆盖至少两天。
- 任何 E6 行只能进入 `PROSPECTIVE_E6_REVIEW_ONLY`。
- 正式训练使用前必须建立新 V2.6 evidence registry、split、seal、readiness audit 和 one-shot formal protocol。

## 当前执行状态

2026-07-11 的 24 条 panel 计算漏斗实跑：

- 24 input -> 4 fast hard-pass -> 4 full -> 4 geometry shortlist；
- cascade 墙钟时间 132 秒；
- guarded local failover 完成 3 条缺失 HADDOCK3，耗时分别为 96、94、93 秒；
- dual-baseline finalize 后 docking imported = 4，已无 incomplete/missing；
- `PV25-0B63D218E0F3`（`zym_test_8787`）为双基线 A/A，最终计算 rank 1；
- `PV25-25F7D6778F87`（`zym_test_108006`）为双基线 A/A，最终计算 rank 2；
- `PV25-8E96BF37FD37`（`zym_test_3633872`）为单 baseline A recheck，rank 3；
- `PV25-EF3F71502C71`（`zym_test_359954`）为 B 类 plausible，rank 4；
- 最终标签计数为 2 `FINAL_POSITIVE_HIGH`、1
  `FINAL_RECHECK_SINGLE_BASELINE`、1 `FINAL_POSITIVE_PLAUSIBLE`；
- 24 条实验样本仍全部是 `PENDING_EXPRESSION_QC`；
- E6 review rows = 0。

这些标签只表示双基线计算几何优先级，不是已验证 binder、blocker 或功能
阳性；冻结的 24 条 prospective panel 不因该标签或 cascade 结果而增删。

完整证据见：

```text
experiments/phase2_5080_v1/audits/PVRIG_V2_5_SCREENING_FUNNEL_AUDIT_20260711.md
experiments/phase2_5080_v1/audits/pvrig_v2_5_screening_funnel_audit_20260711.json
```
