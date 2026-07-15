# PVRIG V4-C 双构象计算代理：执行方案与当前状态

更新时间：2026-07-15 18:15 CST

## 1. 结论

用户提出的 V1.3 冻结、连续指标、软不确定性和新增生物学 anchor 建议是正确的。当前工作分成两条互不替代的路线：

```text
正式科学路线
V1.3 FAIL 保持不变
-> 分析不稳定 anchor
-> 增加独立 blocker family
-> 新方法、新 prospective holdout
-> 条件满足后再启动正式 V3-P2

比赛计算路线
V4-C development surrogate
-> sequence-to-computational-dual-docking rank
-> 只分配昂贵 Docking 预算
-> 不输出 binding/blocking probability
```

必须保留：

```text
FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN
p2_training_ready=false
```

V4-C 不是 PVRIG binding、Kd、competition、实验 blocking 或 Docking Gold 模型。

## 2. 当前数据和任务

当前候选资产：

```text
8,640 raw designs
8,248 exact-unique designs
7,087 fast-gate eligible designs
500 Teacher500 candidates
302 Full-QC hard-pass
290 Full-QC hard-pass with complete AbNatiV
```

新增服务器计算：

```text
/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714

128 candidates x 2 receptors x 3 seeds = 768 jobs
47 controls   x 2 receptors x 3 seeds = 282 jobs
total = 1,050 jobs
```

该协议真正独立对接 8X6B 和 9E6Y，保留 native/cross 2x2 scoring、full/anchor/holdout hotspot、total/CDR3 occlusion、分离的 PVRIG/PVRL2 clash、RMSD、seed 和 model-pair consistency。

2026-07-15 17:55 快照：

```text
SUCCESS               935
RUNNING                  6
PENDING                108
FAILED_MAX_ATTEMPTS      1
controls            282/282 SUCCESS
```

唯一失败 candidate job 仍有同一 receptor 的另外两个成功 seed，不能插补为成功，但可能满足最少 2-seed 门。

## 3. V1.3 的使用边界

V1.3 做对的工程部分继续保留：

- 独立 8X6B/9E6Y Docking；
- ATOM-only 和 HETATM zero gate；
- 固定 Top-8；
- hash closure；
- 无 candidate-specific tolerance；
- receptor、pose 和 seed provenance。

V1.3 只能用于：

- 连续几何诊断；
- receptor gap；
- bootstrap 方差；
- 不稳定 anchor 的 H/O/P 通道分析；
- 下一版方法设计。

不能用于：

- P2 训练标签；
- Docking Gold；
- 实验 blocker label；
- 事后修改阈值后重新声称 PASS。

## 4. dual128 的价值和限制

dual128 是当前最高质量的独立双构象计算证据，但与 7,087 大库存在严重 domain shift：

```text
exact sequence overlap = 0
exact CDR3 overlap      = 0
dual128 scaffold IDs    = 3
7,087 parent clusters  = 40
```

已实现的 label-free support audit 使用：

- SHA256-hashed 3-mer frequency cosine distance；
- CDR3 normalized Levenshtein distance；
- open-development leave-one-family-out 95% 阈值。

实测：

```text
7,087 in-support candidates = 0
in-support fraction         = 0.0
coverage gate >= 0.60       = FAIL
```

证据：

- `experiments/phase2_5080_v1/prepared/pvrig_v4_c/candidate7087_sequence_support.csv`
- `experiments/phase2_5080_v1/prepared/pvrig_v4_c/candidate7087_sequence_support.csv.audit.json`

因此，dual128 可以开发和验证计算 endpoint，但不能直接授权对 7,087 条做 60%-70% model exploitation。

要得到真正可用于大库的模型，下一批独立双构象 teacher 必须来自 Teacher500/Full-QC 290 这一同域候选群。

## 5. 当前 split 的真实口径

当前冻结：

```text
OPEN_DEVELOPMENT                  96
RETROSPECTIVE_GROUPED_CHALLENGE   32
```

group 单位是 `near_cdr3_family_id`，split 代码没有读取新 result-level label。

但在 split artifact 写入前，远程 campaign 已经产生部分结果。虽然本次执行没有查看这些 candidate label，却无法用不可变时间证据证明 hard-coded family 集合从未受标签影响。因此 32 条只能称为：

```text
retrospective grouped challenge
```

不能称为：

```text
untouched formal test
```

冻结产物：

- `experiments/phase2_5080_v1/data_splits/pvrig_v4_c/dual128_candidates_source.tsv`
- `experiments/phase2_5080_v1/data_splits/pvrig_v4_c/dual128_split_manifest.tsv`
- `experiments/phase2_5080_v1/data_splits/pvrig_v4_c/dual128_split_audit.json`
- `experiments/phase2_5080_v1/audits/phase2_v4_c_preregistration.json`
- `experiments/phase2_5080_v1/audits/phase2_v4_c_test_spec.json`

未来任何 formal claim 必须新建版本，并在新 panel 尚无结果时冻结新的 prospective holdout。

## 6. 连续 Teacher 定义

### 6.1 Pose 质量门

每个 native pose 必须：

- HADDOCK score 有限；
- AIR energy 有限；
- native receptor overlay RMSD <= 1.0 A；
- native/cross model pair 完整。

### 6.2 连续效用

```text
soft(x,t) = x / (x+t)

S_base =
  0.15 * clip(full_hotspot / 23, 0, 1)
+ 0.25 * clip(holdout_hotspot / 11, 0, 1)
+ 0.25 * soft(total_occlusion, 500)
+ 0.20 * soft(CDR3_occlusion, 100)
+ 0.15 * soft(CDR3_fraction, 0.15)

PVRIG_clash_reliability =
  1 / (1 + VHH-PVRIG_clash_residue_pairs / 5)

S_pose = S_base * PVRIG_clash_reliability
```

VHH-PVRL2 virtual clash 不作为负惩罚，因为它与阻挡 endpoint 重叠；必须和 VHH-PVRIG 物理 clash 分开保存。

### 6.3 Job、receptor 和 candidate

```text
pose weight = normalized 1/log2(rank+1)
R_job_raw   = weighted mean(S_pose)

model_count_reliability =
  0.5 + 0.5 * min(complete_model_count / 8, 1)

agreement_reliability =
  0.5
  + 0.25 * native_cross_support_agreement
  + 0.25 * model_pair_consensus

R_job = R_job_raw
        * model_count_reliability
        * agreement_reliability

R_receptor  = median(R_job across successful seeds)
R_dual_mean = mean(R_8X6B, R_9E6Y)
R_dual_min  = min(R_8X6B, R_9E6Y)
R_dual_gap  = abs(R_8X6B - R_9E6Y)
```

主 development target 是 `R_dual_min`。G1-G5 只保留为解释层。

Open teacher builder：

- 在读取 raw result JSON 前先物理筛出 96 个 open candidate IDs；
- 不计算 32 条 challenge label；
- 只打开所选 job 的 raw `job_result.json`；
- 强制 evaluator `PASS + unlockable=true + all gates PASS`；
- 强制 job/results/pose/protocol/candidate/split hash binding；
- 强制最少 2 seeds 和最少 4 complete models。

实现：

- `experiments/phase2_5080_v1/src/prepare_phase2_v4_c_teacher.py`
- `experiments/phase2_5080_v1/src/test_prepare_phase2_v4_c_teacher.py`

## 7. Baseline 和模型

已实现 baseline：

1. constant；
2. scaffold-only；
3. metadata shortcut；
4. CDR3-only ridge；
5. full-sequence handcrafted ridge；
6. frozen `v3_full` generic-prior-only（分数完成后加入）；
7. 100 次 near-CDR3-family-level permutation null。

V2.3 contact-statistics 尚无冻结的 V4-C feature extractor，因此从 v1 gate 中明确排除，而不是写成“if available”。

开发估计使用 nested grouped CV：

```text
outer 5-fold near-CDR3-family CV
inner 4-fold near-CDR3-family alpha selection
alpha grid = 0.01, 0.1, 1, 10, 100
```

唯一 primary development metric：

```text
Spearman(R_dual_min)
```

最强 baseline 必须包含 metadata shortcut。NDCG、top-quartile recall 和 MAE 只作固定 tie-break。

当前 32 条 challenge 只能做一次描述性检查；读完后本版本关闭，不能根据 challenge 再决定是否增加 cross-attention。任何新架构都要新版本和新 panel。

实现：

- `experiments/phase2_5080_v1/src/train_phase2_v4_c_baselines.py`
- `experiments/phase2_5080_v1/src/test_train_phase2_v4_c_baselines.py`

## 8. OOD、uncertainty 和部署门

V4-C 的 broad-use gate 已冻结：

- 7,087 in-support fraction >= 0.60；
- Teacher500 grouped Spearman >= 0.25；
- 比 Teacher500 最强 shortcut 至少高 0.05；
- 去掉最高不确定性 25% 后，MAE 至少下降 10%；
- 最高不确定性 quartile 的 MAE 至少是最低 quartile 的 1.25 倍。

当前 coverage 为 0，已经明确失败。因此在新的同域 independent-dual teacher 完成前：

```text
dual128-derived surrogate exploitation on 7,087 = 0
```

V4-C 仍可用于：

- dual128-like 局部研究；
- endpoint 和 uncertainty 代码验证；
- 设计下一批同域 independent dual-redocking panel。

## 9. 真正面向大库的下一批数据

下一批应从 Full-QC 290 中建立同域独立双构象 panel，而不是继续把 3-scaffold dual128 外推到 40-parent 大库。

推荐：

```text
Full-QC complete 290
-> 保留原 parent-cluster train/dev/test 分组
-> 8X6B x 9E6Y independent docking
-> 3 seeds per receptor
-> 290 x 2 x 3 = 1,740 jobs
```

这批数据有三个关键优势：

1. 与 7,087 大库同一生成域；
2. 26 个 surviving parent clusters，而不是 3 个 scaffold；
3. 已有 NanoBodyBuilder2 monomer，远程路径可复用，不需重新建全部单体。

旧 P1 test 的独立双构象新标签尚未生成，因此可以在新 campaign 启动前，把 parent-cluster split、continuous target、model 和 evaluator 全部重新冻结，建立真正 prospective 的新 endpoint test。

## 10. 已启动的计算

### Node23

- 原 1,050-job controller 保持运行；
- controls 已全部完成；
- watcher 等待全部 terminal 后才运行 fresh aggregate；
- watcher 现在要求 status known-state 总数精确等于 1,050；
- evaluator readiness 与 P2/P3/P4 enrichment 分开记录。

### Node1

- 原 Full QC 和 parity 副本保持运行；
- GPU 0 正在为 dual128 生成冻结 `v3_full` generic weak prior；
- 该 prior 只作为独立 baseline，不进入几何真值。

## 11. 比赛 timebox

V4-C 比赛决策截止：

```text
2026-07-20 18:00 CST
```

到时若没有新的同域 dual teacher 和可信 validation：

```text
自动回退
= v3_full weak prior
+ Full QC
+ uncertainty
+ parent/patch/mode/CDR3 diversity
+ real docking
```

V4-C 科研工作可以继续，但不得阻塞 Top50/Top10。

## 12. 当前不能做的事

- 不能修补 V1.3 为 PASS；
- 不能用 stale aggregate；
- 不能把 47 controls 当 47 个独立 biological anchors；
- 不能把当前 32 条称为 untouched formal test；
- 不能让 challenge 结果驱动同版本继续调模型；
- 不能把 dual128 模型直接用于 7,087 的大比例 exploitation；
- 不能把 Docking geometry 写成实验 binding/blocking。

最终判断：当前 1,050-job 数据很有用，但主要用于冻结和验证计算 endpoint。label-free OOD 审计已经证明它与 7,087 大库不在同一支持域。要实现用户真正需要的“大范围预测模型”，下一步不是放大网络，而是立即准备 Full-QC 290 的同域独立双构象 redocking 数据，再用简单 baseline -> frozen embedding model -> 新 prospective holdout 的顺序训练。
