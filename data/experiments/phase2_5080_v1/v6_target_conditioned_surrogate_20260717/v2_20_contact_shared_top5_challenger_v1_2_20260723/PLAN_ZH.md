# V2.20 Contact-Shared Top5 Challenger：数据盘点与执行计划（草案）

## 0. 状态和不可越过的边界

本目录目前只有研究规划和预注册草案：

```text
DRAFT_ONLY
NOT_FROZEN
NO_TRAINING_AUTHORIZED
NO_TEST_ACCESS_AUTHORIZED
```

V2.20 的目标是利用真实独立双受体 Docking Top-K pose 产生的 residue-contact 辅助监督，改善序列/单体结构 surrogate 对计算几何的 **Top 5% 早期富集**。它仍只预测：

```text
independent 8X6B / 9E6Y computational Docking geometry
```

它不预测结合、Kd、实验竞争、实验阻断、表达、纯度或 Docking Gold。

冻结的 V2.13 Phase-B/C1、既有 whole-parent fold、开发集和 frozen test 均不得因本草案修改。V2.20 必须另起版本、另建 runtime；在完整实现审查和正式 freeze 前不得启动训练。

---

## 1. 当前 canonical 训练和 Top5 基线

### 1.1 Scalar teacher

本地 canonical teacher：

```text
experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/
  v2_10_canonical10644_training_v1_20260721/prepared/
  primary_D1_canonical10644_teacher.tsv
```

关键闭包：

- 10,644 条 open teacher：9,849 train + 795 open development；
- 54 个 train parent + 10 个 development parent；
- 直接监督固定为 `R_8X6B`、`R_9E6Y`；
- 推理主目标固定为 `R_dual_min = min(R_8X6B, R_9E6Y)`；
- frozen test 不在这个 teacher 中；
- teacher SHA256：`46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3`；
- split manifest SHA256：`9dc416dcf8694f321a5432ba8574f0229c03527af14926fcf2f43ee4211f07ed`。

### 1.2 必须击败的同协议基线

V2.13 L1 seed43 strict whole-parent 5-fold OOF：

```text
EF_true_top10_at_budget5 = 3.0828512885987585
hits / selected          = 152 / 493
precision@5              = 0.3083164300
recall@5                 = 0.1543147208
R_dual Spearman          = 0.5661935645
R_dual MAE               = 0.0362309829
```

证据：

```text
experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/
  v2_13_top5_enrichment_v1_20260722/results/top5_campaign_20260722/
  status/V2_13_PHASE_A_TERMINAL.json
```

该 terminal 的 SHA256 为：

```text
fdacc02b392274bc4451bd5abdfb273657ac5da86859532dec200ee24d4b514c
```

`EF@5 = 5.0` 仍是最终工程目标，不得在结果出现后下调。V2.20 首先必须在完全相同的 9,849 行、whole-parent folds、seed43 和 evaluator 下证明相对 L1 的增量。

---

## 2. 已定位的 residue-contact 数据

## 2.1 V4-D：最干净的完整多 seed teacher

本地已发布包：

```text
experiments/phase2_5080_v1/prepared/
  pvrig_v6_v4d_open226_contact_teacher_v2_20260718/
```

源 Docking root：

```text
/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
```

已验证统计：

| 项目 | 数量 |
|---|---:|
| teacher candidates | 226 |
| parent clusters | 20 |
| 完整 3-seed candidates | 225 |
| 一侧只有 2 seed 的 candidates | 1 |
| successful jobs / scheduled jobs | 1,355 / 1,356 |
| valid Top-8 pose records | 12,640 |
| pair rows | 132,874 |
| residue marginal rows | 55,138 |

协议：8X6B + 9E6Y，seeds 917/1931/3253，每 job 固定 Top-8，4.5 Å contact cutoff，pose rank 权重为归一化 `1/log2(rank+1)`，seed 等权聚合并保存 pair variance。

与当前 canonical10644 按 `sequence_sha256` 精确闭合后：

| 当前 D1 归属 | candidates | parents |
|---|---:|---:|
| train | 113 | 11 |
| development | 76 | 6 |
| 合计 | 189 | 17 |

V4-D 唯一的部分 seed candidate 不在 canonical10644，因此 189 个闭合候选都是完整 3-seed。

关键输出哈希：

```text
pair teacher     39b600e6979e72ef89237070b36a1f7afaecb4be5be4735d1650d55cd17811a8
residue marginal 1f5906df603fdbaea166c992c93bb4ff1b95c22cccff80739cedbc892a6c6e8e
pose inventory   32ea99b24277726328ba5303a532ba7cb053790588b5267beef85edf7265a042
```

## 2.2 V4-H：大规模自适应 multi-seed teacher

本地已发布包：

```text
experiments/phase2_5080_v1/prepared/
  pvrig_v4_h_adaptive_contact_teacher_v2_20260718/
```

源 Docking root：

```text
/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717
```

已验证统计：

| evidence tier | candidates |
|---|---:|
| DUAL_3_SEED | 123 |
| DUAL_2_SEED | 241 |
| DUAL_1_SEED | 917 |
| TECHNICAL_INCOMPLETE | 39 |
| analyzable total | 1,281 |

其他闭包：

- 11 parent clusters；
- 3,536 paired receptor/seed jobs；
- 27,719 selected pose coordinate files；
- 528,328 residue-pair rows；
- 317,518 residue marginal rows；
- 25 条存在 receptor seed-set asymmetry，提取器只使用双 receptor 成对成功 seed；
- unmatched/technical job result 和 pose 打开计数均为 0。

与 canonical10644 精确闭合：

| tier | current train | current development |
|---|---:|---:|
| DUAL_3_SEED | 107 | 0 |
| DUAL_2_SEED | 213 | 0 |
| DUAL_1_SEED | 849 | 0 |
| 合计 | 1,169 | 0 |

因此 V4-H 可直接提供 320 条 current-train high-reliability（2/3 seed）contact teacher；849 条 single-seed 只能作为后续低权重 ablation，不能与 multi-seed 主 teacher 等权。

关键输出哈希：

```text
pair teacher     9d27d2297822e978fe969bb645fee97a76ede544de902f6dfe6051c88a33ec92
residue marginal 7b79b07b7b052e518293ec98c5f4b5a79e4f5f0710950ae219a4205a8aff5a7f
candidate state  47fc2eb0ee6bae43369bf774d47c490874ceb6dbe04f0fbaece95cd61c8d33e5
```

## 2.3 V29 canonical release：scalar 很完整，但 pose PDB 只部分留在 Node1

Node1 canonical release：

```text
/data1/qlyu/projects/pvrig_v29_canonical_training_release_v1_20260721
```

关键文件：

```text
release/pvrig_v29_sequence_docking_weaklabels.tsv
reports/candidate_seed_dual_labels.tsv
reports/canonical_job_results.tsv
reports/canonical_top8_pose_scores.tsv
```

已验证统计：

| 项目 | 数量 |
|---|---:|
| unique candidates | 9,934 |
| parent clusters | 65 |
| successful jobs | 24,815 |
| technical NA jobs | 11 |
| unique physical Top-8 poses | 196,648 |
| DUAL_3_SEED candidates | 494 |
| DUAL_2_SEED candidates | 1,486 |
| DUAL_1_SEED candidates | 7,948 |

发布包中的 196,648 个 pose rows 均标记：

```text
PATH_RECORDED_PDB_HASH_NOT_MIRRORED
```

而且 `pose_pdb_sha256` 全为空。因此 **不能仅凭 canonical_top8_pose_scores.tsv 声称三维 contact teacher 已闭合**。

来源分解：

| selected source | successful jobs | unique physical poses | Node1 pose 可用性 |
|---|---:|---:|---|
| lab | 10,240 | 80,048 | 实查 10,240/10,240 jobs 的全部 Top-K PDB 非空存在 |
| stage2 | 10,493 | 83,944 | 原 `/tmp/als001821/...` 路径在 Node1 不存在 |
| external | 3,348 | 26,784 | PDB 未镜像；路径不具备闭合性 |
| stage3 | 734 | 5,872 | 原 `/tmp/als001821/...` 路径在 Node1 不存在 |

lab PDB 当前位于：

```text
/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720/runs/<job_id>/
  haddock_run/6_seletopclusts/<model>.pdb.gz
```

按以下严格定义：

```text
同一 candidate + seed
同时具备 8X6B 和 9E6Y SUCCESS
两侧所有已选择 Top-K PDB 均为非空 regular file
```

Node1 当前可产生的 local-coordinate paired-seed 候选为：

| split | >=2 paired seeds | parents | 其中 3 paired seeds |
|---|---:|---:|---:|
| train | 312 | 44 | 55 |
| development | 44 | 9 | 8 |
| 合计 open | 356 | 53 | 63 |

其中 7 个 train candidates 的本地成对 seed 是 `1931+3253`，不包含 scalar 主标签 seed917。为了让 contact auxiliary 和 `R8/R9_primary_seed917` 口径一致，V2.20 主 challenger 暂定排除这 7 条，仅保留：

| split | >=2 paired local seeds 且包含 seed917 |
|---|---:|
| train | 305 |
| development | 44 |
| 合计 | 349 |

V29 关键 SHA256：

```text
RELEASE_RECEIPT.json                  2f5f9622802262ce67749ea0436653200e6dfbd077920b61c52b511fb63db8c6
release weaklabels                    2ffd88625a50b757f5a291a7bbea99632a39db636e8dba570dea890ea95945d4
candidate_seed_dual_labels            7974f53f453cb56f02d7a5e10d37209c527dc9bea06e4164d946123c1f45cb7d
canonical_job_results                 4d3a8c858de78683345c7bd7f3e9f06f801d55ce6953c776f22debbc84b9fd3c
canonical_top8_pose_scores            da82a28e5b477bc31a3d4fbb1db8a88ffefd501291d3ee721eb6465b5312db7a
```

---

## 3. 可构建的 high-reliability contact teacher 规模

### 3.1 与 canonical10644 对齐后的最大开放集合

```text
V4-D exact-match multi-seed: 189
V4-H exact-match 2/3-seed:  320
V29 local-coordinate >=2:  356
--------------------------------
open high-reliability total: 865
```

分拆：

```text
train:       745 candidates
  3-seed:   275
  2-seed:   470

development:120 candidates
  3-seed:    84
  2-seed:    36
```

共覆盖 62/64 个 open parent；缺少 `C0052` 和 `C0076`。

### 3.2 建议的 primary teacher

为了与 scalar seed917 对齐，主 challenger 排除 V29 的 7 个 `1931+3253` contact-only candidates：

```text
primary train contact teacher: 738 candidates
primary development contact:   120 candidates（只允许冻结后一次性评估）
```

primary train 覆盖 53/54 个 train parents；唯一没有 high-reliability contact 的 train parent 是 `C0052`。

### 3.3 为什么现在可以做，但还不能直接训练

**可以做**：

- V4-D/V4-H 已经有 pair mean、variance、uncertainty、seed provenance 和 Top-K pose inventory；
- V29 lab 有 349 条与 primary seed 对齐的双 receptor multi-seed candidate；
- 合并后的 primary train contact teacher 已足够覆盖 53/54 train parents，不再只是少数 parent 的小样本辅助任务。

**不能直接训练**：

- V29 lab 的 PDB 尚未逐文件写入 content-addressed hash manifest；
- V29 还没有使用与 V4-D/V4-H 完全相同的 4.5 Å、Top-K rank-weighted contact extractor 输出 pair/marginal teacher；
- contact availability 来自自适应 multi-seed 选择，存在 acquisition bias；
- sparse pair TSV 只记录有过 contact 的 pair，必须在候选/receptor 完整闭包后才可把未出现 pair 当作 0，不能把技术缺失当负例；
- current development 的 contact 标签不得用于损失权重、架构或超参数选择。

---

## 4. V2.20 建议架构

## 4.1 输入保持 label-free

沿用 V2.13 L1 的生产输入：

```text
frozen ESM2-650M VHH residue states
+ label-free VHH monomer graph
+ fixed public 8X6B target graph
+ fixed public 9E6Y target graph
```

禁止 forward 输入：

```text
candidate_id / parent_id / campaign_id / teacher_source
contact availability / seed count / reliability tier
Docking pose / pose-derived scalar / true contact target
M2 outputs / C2 outputs
```

contact teacher 只用于训练 loss mask 和 loss weight，不得在推理时成为必需输入。

## 4.2 Attention 与 contact 必须正交到最后 logits

复用已技术 smoke 通过的 V2.5 orthogonal head 设计：

```text
shared VHH/target encoders
        ├── attention interaction → attention logits + conformer-specific temperature
        │                         → attention-routed pools → R8 / R9
        └── contact interaction   → separate pair logits + receptor bias/calibration
                                  → marginal / pair contact losses
```

硬约束：

- attention logits 与 contact logits 不共享最后的投影、terminal scalar、bias 或 temperature；
- contact prediction 不直接回灌 scalar pooling；
- primary challenger 只允许 contact gradient 更新 shared encoders；
- 必须用 gradient-role audit 证明：
  - scalar loss → contact-only parameters 的 gradient 为 0；
  - contact loss → attention/scalar-only parameters的 gradient 为 0；
  - contact loss → shared encoder 的 gradient非 0。

## 4.3 输出只直接预测 R8/R9

```text
pred_R8, pred_R9 = direct neural outputs
pred_Rdual       = exact min(pred_R8, pred_R9) at evaluation/inference
```

训练可继续使用 `softmin_tau=0.02` 辅助梯度，但禁止训练第三个独立 `R_dual` head。

## 4.4 Loss

所有 9,849 fit rows 使用 V2.13 L1 scalar loss：

```text
L_scalar = top-weighted Huber(R8) + top-weighted Huber(R9)
         + 0.5 * softmin auxiliary
```

只有当前 outer-fit parents 中存在 primary contact teacher 的行使用：

```text
L_contact = w_m * uncertainty-weighted marginal soft BCE
          + w_p * uncertainty-weighted pair soft BCE
```

建议固定关系：

```text
w_p = 0.5 * w_m
3-seed tier weight = 1.0
2-seed tier weight = 0.8
pair/residue weight *= 1 / (1 + 4 * seed_variance)
```

`w_m` 不从 OOF EF@5 网格中选择。正式 freeze 前用不读取 prediction metrics 的 pre-optimizer gradient calibration，从冻结候选网格中选择使 shared-encoder contact gradient 占合并梯度 5%–15% 的最小权重；若没有权重满足门，V2.20 fail-closed，不启动 OOF。

Pair negatives：

- 只有 candidate/receptor teacher state 完整时，闭合目标 residue universe 内未出现的 pair 才可定义为 0；
- 每 candidate/receptor 固定采样 positive:negative = 1:3；
- negatives 在 interface/hotspot 与 off-interface 间分层，避免全部为简单远端负例；
- technical NA、unpaired seed、缺失 PDB 不产生负样本。

---

## 5. 严格评估设计

## 5.1 Phase 0：只构建 teacher，不访问模型指标

1. 对 V29 lab 10,240 jobs 重算所有 Top-K PDB SHA256；
2. 先按 canonical split/status 过滤，再打开 pose：
   - train 允许；
   - development 输出到独立 sealed 包；
   - frozen test / quarantine pose 打开计数必须为 0；
3. 使用与 V4-D/V4-H 相同的 contact cutoff、Top-K、pose rank 和 seed 聚合公式；
4. 输出 pair teacher、dense VHH marginal teacher、pose inventory、content-addressed PDB manifest、audit 和 receipt；
5. 按 `sequence_sha256 + parent_framework_cluster + receptor + seed` 与 canonical10644 闭合；
6. 物化 738-row primary train contact mask，不新增或删除任何 scalar row。

## 5.2 Phase 1：同 seed、同 folds 的单变量 challenger

固定：

```text
rows        = 9,849
parents     = 54
outer folds = exact V2.13 whole-parent five folds
seed        = 43
base loss   = V2.13 L1
```

比较：

```text
B0 = frozen V2.13 L1 reference
C1 = same architecture/loss + high-reliability contact-shared auxiliary
```

contact label 只能来自该 outer fold 的 fit parents。outer-score parent 的 scalar 和 contact label都不得进入 fit。不能用全体 contact teacher 先预训练再做 OOF，因为这会把 score-parent pose 信息泄漏进 shared encoder。

## 5.3 Primary metric 和安全指标

Primary：

```text
EF_true_top10_at_budget5
```

同 V2.13 evaluator：9,849 条中真值 Top10%=985，预算 Top5%=493。

同时报告：

- hits/493、precision@5、recall@5、binary NDCG@5；
- EF@10；
- Rdual Spearman/MAE；
- 5 个 outer-fold EF@5、median、worst；
- parent bootstrap `ΔEF@5(C1-B0)` CI；
- contact marginal AUROC/AUPRC/Brier（只在 outer-score parent 且有 contact teacher 的子集）；
- hotspot/contact mask shuffle ablation；
- target conformer swap、target residue permutation；
- prediction changes on the non-contact-supervised parent `C0052`。

## 5.4 Draft promotion gate

正式 freeze 前仍需 reviewer 冻结精确门槛。当前建议：

```text
C1 pooled EF@5 > 3.0828512886
C1 pooled EF@5 target = 5.0
bootstrap 95% CI for ΔEF@5 lower bound > 0
>=4/5 folds have EF@5 delta >= -0.25
worst fold delta >= -0.75
EF@10 >= 2.5652  (不低于 L1 的95%)
Rdual Spearman >= 0.5362
Rdual MAE <= 0.03985
contact/hotspot shuffle must materially reduce contact metrics
frozen test access count = 0
open development access count during selection = 0
```

若 C1 失败，不修改阈值，不挑单个漂亮 fold，不读取 development 后回调 loss 权重；保留 L1 为生产基础模型。

## 5.5 Phase 2：只有 C1 通过后才做多 seed

固定 seeds：

```text
43, 917, 1931
```

先分别平均 R8/R9，再 exact min；不得剔除坏 seed。Phase 2 仍使用 whole-parent OOF。多 seed 完成并冻结后，open development 795 才可做一次性描述性评价。

---

## 6. 主要风险与防护

| 风险 | 影响 | 防护 |
|---|---|---|
| contact 与 scalar 来自同一 Docking | 不是独立生物学信息 | 明确只称 teacher densification；仍需 prospective Docking |
| multi-seed acquisition 是自适应选择 | contact 子集偏高分 | contact availability 不入 forward；whole-parent OOF；保留 V4-D 全量多 seed；报告 teacher/no-teacher 分层 |
| V29 非 lab PDB 未镜像 | 不能重算 residue contact | 当前只消费 lab 10,240 jobs；其余 fail-closed |
| V29 pose hash 为空 | 无不可变坐标闭包 | 训练前生成 content-addressed pose manifest |
| sparse pair 表被误解为全负闭包 | 产生伪负样本 | 只有 valid candidate/receptor 全 universe 内缺失 pair 才为 0 |
| original V4-D split 与 current D1 不同 | parent leakage | 一律继承 current canonical10644 whole-parent fold |
| development / test 污染选择 | 夸大 EF@5 | selection 阶段 access count 必须为 0；先 filter 后 parse/open |
| contact loss 压过 scalar | EF@5 退化 | label-blind gradient calibration；5%–15% shared-gradient gate |
| contact head 偷偷成为 scalar输入 | 将 teacher proxy 直接喂给主头 | `contact_feedback_to_scalar=false` + gradient audit |
| C0052 无 high-reliability contact | 部分 parent 无辅助监督 | 单独报告 C0052；不以 parent ID 或 missingness 为输入 |

---

## 7. 下一步实施顺序

1. 对本 draft 做 architecture/data-leakage review；
2. 实现只读 V29 lab contact extractor 和 content-addressed receipt；
3. 写 teacher closure tests：行数、parent、seed、receptor、PDB hash、split-before-open；
4. 物化 738-row train contact mask和独立 sealed 120-row development contact 包；
5. 实现 C1 runner，并复用 V2.13 evaluator；
6. 运行 pre-optimizer gradient calibration，不读取 prediction metrics；
7. 冻结正式 preregistration、implementation hashes 和 exact gates；
8. 仅 seed43 × 5 folds 运行 C1；
9. 通过 gate 才进入 3-seed；失败则保持 L1，不事后调门；
10. 预测冻结后才做一次 open development 描述性验证；frozen test 继续封存。

## 结论

**可以构建 high-reliability multi-seed Top-K contact teacher。** 当前主训练可安全规划为 738 条、53/54 train parents；若不要求 seed917 对齐则最大为 745 条。加上 120 条只允许冻结后使用的 development contact，开放集合最多 865 条。最大的工程阻塞不是样本数，而是 V29 lab pose 的不可变哈希闭包和严格 split-before-open extractor 尚未实现。
