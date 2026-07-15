# PVRIG 比赛目标、训练测试回顾与下一步路线

**更新时间：** 2026-07-15
**比赛截止：** 2026-07-26 18:00
**当前建议状态：**

```text
TARGET_CONDITIONED_DESIGN_POOL_READY
TEACHER500_DOCKING_READY
MODEL_FRONTSCREEN_NOT_VALIDATED
DOCKING_GOLD_NOT_RELEASED
FINAL_SUBMISSION_PORTFOLIO_NOT_FROZEN
```

## 1. 一句话结论

我们已经完成了从数据治理、contact/site 学习、generic binding prior、PVRIG 条件化设计、Teacher500 docking、V3-P1 形状代理模型，到独立双受体 Docking Gold V1.3 验证的全链路。这条链路在工程上已经闭包，但三个科学问题仍然没有解决：

1. pair/binding 排序的泛化性仍弱；
2. V3-P1 的排序信号可能主要来自 VHH/parent/generator shortcut，而不是 PVRIG 条件依赖；
3. 双受体 G1-G5 离散几何标签的 bootstrap modal stability 不足，因此不能发布为 Docking Gold 或 P2 training label。

但比赛最初的目标不是“训出一个完美的阻断预测器”，而是在截止日前交付 50 条可追溯、可表达、尽可能结合 PVRIG 并阻断 PVRIG-PVRL2 的 VHH，尤其要提高 Top10 中“至少一条成功”的概率。

所以当前比赛主线应立即从“继续训模型”切换为：

```text
Teacher500 全量 full QC
-> 100-150 条多样性 shortlist
-> 独立 9E6Y native docking / Top20 replicate
-> 多轴 Pareto + portfolio 选择
-> 冻结 Top50 / Top10 / 提交包
```

V3-P2 研究、新 Docking Gold 方法和新 active-learning teacher 不应再阻塞本次比赛提交。

## 2. 最初比赛目标

### 2.1 交付物

第一轮需要：

1. 50 条按预测优先级排序的 VHH 序列；
2. 每条的设计类型：从头设计或优化改造；
3. parent/scaffold、变更位点、CDR before/after、设计方法和设计理由；
4. IMGT/CDR、official validator、已知阳性 CDR identity、developability 和聚类信息；
5. Top10 的单体结构、复合物 pose、8X6B/9E6Y 证据、人工复核和风险说明；
6. 1 页方案摘要和可重现 release。

比赛详细边界见：

- `node1/PVRIG_COMPETITION_ASSET_AND_GOAL_AUDIT_20260712.md`

### 2.2 生物学目标

目标不是任意 PVRIG binder，而是同时增加：

```text
表达/纯化成功
AND 结合 PVRIG
AND 亲和力足够
AND 结合位置和角度可阻断 PVRIG-PVRL2
AND 无明显序列或结构风险
```

必须分开：

- `binding prior`：序列/模型对结合可能性的弱先验；
- `pose quality`：预测复合物是否合理；
- `affinity`：最终由 Kd 实验确定；
- `blocker-like geometry`：计算姿态是否遮挡 PVRL2 界面；
- `experimental blocking`：最终由 competition/IC50/功能实验确定。

### 2.3 评分对齐

比赛初筛：

```text
BLI 单浓度结合 70%
+ 表达量 20%
+ 纯度 10%
```

复筛：

```text
Kd 50%
+ IC50 50%
```

因此 Top10 不能全是“几何最极端但可能不结合”的序列，也不能全是同一 parent/CDR3 家族的近重复。

## 3. 原始技术假设与实际执行

我们最初将模型拆为两层：

```text
V3-G：generic target-conditioned binding/contact prior
V3-P：PVRIG geometry-surrogate frontscreen
```

然后由 Node1 作为昂贵 teacher：

```text
序列/QC
-> VHH 单体
-> HADDOCK
-> PVRL2 occlusion
-> 8X6B/9E6Y 几何
```

这个总体架构已经真正实现。执行结果不是“pipeline 没跑完”，而是通过预注册和 formal gate 证明了：

- contact/paratope 是可复用的学习能力；
- generic pair/binding 只能作弱先验；
- docking surrogate 学到了一定 teacher 排序信号，但 target dependence 不足；
- G1-G5 不能直接升格为已验证的 Gold label。

## 4. 训练和测试时间线

| 阶段 | 主要数据/模型 | 关键结果 | 结论 |
| --- | --- | --- | --- |
| Phase 1 / V1 | ZYM site 标签、weak contact、构造 pair BCE；AA+位置 Transformer | paratope/epitope/weak-contact AUPRC `0.6244/0.1541/0.6863`；pair AUROC/AUPRC `0.5153/0.2684` | 完成基线，pair 基本无识别力 |
| V2 | SAbDab2 真实重原子 contact；160 structures / 371 records | contact AUROC/AUPRC `0.8728/0.6559`；pair `0.5180/0.2708` | 真实 contact 明显可学，pair 仍弱 |
| V2.1 | 800 structures / 2,725 records | contact `0.8617/0.6157`；paratope/epitope `0.6411/0.1839` | 扩数据后 site 改善，pair 无根本变化 |
| V2.2 | 2,259 structures / 8,414 contact records / 855,922 positive residue pairs | contact AUROC/AUPRC `0.8975/0.7242`；paratope `0.6477`；epitope `0.2272`；pair `0.5833/0.3338` | 早期 contact/site 最强版本；但 split 和 pair 语义较宽松 |
| V2.3 strict | frozen ESM2 residue + CDR mask + 双向 cross-attention + bilinear contact；global cluster split；3 seeds | contact AUPRC `0.5197`；paratope `0.6306`；epitope `0.1598`；MRR `0.5249` < random `0.5330` | contact/site 信号成立，pair ranking 接近随机 |
| V2.4 | V2.3 warm start + complete-group listwise；1,230 groups / 4,844 rows | contact/paratope/epitope `0.5323/0.6418/0.1611`；MRR `0.5192` < random `0.5330`；pose `2/50` | listwise 没修好 pair ranking；不能宣称 binder/blocker classifier |
| V2.5 | 10,324-row evidence registry；NanoBind 181 affinity pairs；frozen pooled ESM2 + shallow ordinal ranker | 3 seeds 相对 cosine 点估计均为正，但 CI `[-0.0175,0.2905]`，permutation `p=0.3019` | `PASS_LIMITED_RANKING_ONLY`；PVRIG `DATA_NOT_READY_FOR_TARGET_MODEL` |
| 初代 V3 mean-pool | VHHBERT 768 + ESM2 VHH/Ag 320 + physchem；gated pair interaction | dev macro AP `0.5847` > `0.5396`；sealed hTNFa `0.1715` < baseline `0.2253` | dev 改善未迁移，formal fallback |
| V3-G2 residue | 138,926 real assay pairs；18,444 VHH clusters；111,206/13,933/13,787 cluster-safe split | ensemble macro target AP `0.2443` < mean-pool `0.3415`；delta CI `[-0.1802,-0.0381]`；target contrast win `0.6222` | target dependence 有信号，但 generic 排序不如 mean-pool，回退弱先验 |
| Teacher500 | 40 parents x 3 patches x 2 modes；500 candidates / 4,394 poses | 500/500 complete；stable G1/G2/G3/G5=`13/339/135/13` | 形成 prospective docking teacher；仍非 binding/blocking truth |
| V3-P1 | frozen V2.3 residue backbone + mean-pool prior + PVRIG hotspot/8X6B/9E6Y features + ordinal/geometry/contact heads | NDCG `0.9877` > `0.9209`，Spearman `0.5215`；但 target-control 下降 `0%/0%/0%/12.5%`，perm `p=0.0725` | `FAIL_V3_P1_FORMAL_SURROGATE_GATE`；shortcut 风险，不部署 |
| Docking Gold V1.1 | Pilot64 双受体/重复运行 | run/postprocess 闭包不全，kappa 不可定义 | `FAIL_DOCKING_GOLD_NOT_VALIDATED` |
| Docking Gold V1.2 | recovery + family-aware calibration | 多数门通过，bootstrap modal `7/11` < required `9/11` | 冻结失败 RC，不改写 |
| Docking Gold V1.3 | 47 cases x 2 native receptors；94 runs；752 Top-8 poses | new runs `30/30 PASS`；LOFO `0.9333`；receptor consistency `11/11`；modal `6/11` < `9/11` | 执行成功，科学门失败；Gold/training/P2 全锁定 |

## 5. 关键模型和数据详解

### 5.1 V2.2：证明“哪些残基可能接触”可以学

V2 系列使用了真实结构中 `<=4.5 A` 的重原子接触作正例，`>=8 A` 作负例。模型包含：

- VHH 和 antigen residue encoder；
- 双向 cross-attention；
- paratope/epitope head；
- bilinear residue-pair contact head；
- 聚合 contact 信号的 pair head。

V2.2 使用 RTX 5080 完成，产物：

- `experiments/phase2_5080_v1/reports/phase2_v2_2_full2277_eval.md`
- `experiments/phase2_5080_v1/reports/phase2_v2_2_full2277_metrics.json`
- `experiments/phase2_5080_v1/audits/structure_contact_maps_v2_full2277_summary.json`

最重要的教训是：较好的 contact/site AUPRC 不会自动变成较好的 whole-pair binding rank。

### 5.2 V2.3/V2.4：修严 split 后，pair ranking 接近随机

V2.3 使用 frozen ESM2-8M residue embedding、CDR type mask、双向 cross-attention 和 detached contact feature。数据按 exact VHH、VHH cluster、CDR3 cluster、antigen family/PDB 做全局隔离。

三个 seed 上 contact/paratope 稳定高于 prevalence，但 MRR 低于精确随机期望。V2.4 增加 listwise 目标后没有修复，只改善了少量 contact/site 指标和 candidate rank stability。

因此：

- V2.3/V2.4 residue/contact backbone 可作特征提取器；
- pair score 不能主导 full-QC 名额；
- V2.4 Top50 公开 ZYM 序列只验证了流程，不是合规提交序列。

产物：

- `experiments/phase2_5080_v1/reports/PHASE2_V2_3_STRICT_EVALUATION_V1.md`
- `experiments/phase2_5080_v1/reports/PHASE2_V2_4_STRICT_EVALUATION_V1.md`

### 5.3 V2.5：证明“没有真实 PVRIG label 就不应强训 target model”

V2.5 将证据分为 E0-E5，建立 10,324 行 canonical registry。PVRIG 只有 11 条 control/calibration evidence，没有可用的 verified binder/nonbinder/ranking groups。

小型 generic affinity ranker 的三 seed 点估计为正，但 CI 跨 0，permutation 不显著。所以正确结论是：

```text
generic: PASS_LIMITED_RANKING_ONLY
PVRIG:   DATA_NOT_READY_FOR_TARGET_MODEL
```

24 条 prospective assay panel 已冻结，但当前仍是 `PENDING_EXPRESSION_QC`，不能当作已有实验标签。

### 5.4 V3-G：generic target-conditioned model 有信号，但不足以主导候选

初代 V3 mean-pool 输入：

- VHHBERT mean-pooled VHH 768d；
- ESM2 VHH 320d；
- ESM2 antigen 320d；
- physchem features；
- `[v, a, v*a, abs(v-a), cosine]` interaction。

它在 development 上好于 ESM2 pair baseline，但在 sealed hTNFa 上反转。V3-G2 改为 cluster-safe residue-level 模型后，target contrast 和 contact/site replay 过门，但总体 binding rank 仍显著差于 mean-pooled baseline。

因此当前生产用法只能是：

```text
mean-pooled v3_full = weak generic prior / tie-breaker
residue/contact      = interface feature source
neither              = calibrated PVRIG binder probability
```

产物：

- `experiments/phase2_5080_v1/reports/PHASE2_V3_ARCHITECTURE_PLAN.md`
- `experiments/phase2_5080_v1/runs/phase2_v3_g2_final_evaluation_v1/final_evaluation_summary.json`

### 5.5 Teacher500 和 V3-P1：整个微调计划已经真正执行

已完成的条件化设计库：

```text
40 parent framework clusters
x 3 PVRIG patches
x 2 design modes (H3 / H1H3)
x 12 RFdiffusion backbones
x 3 ProteinMPNN sequences
= 8,640 raw candidates
```

实际数量：

```text
8,640 raw
8,248 exact-unique
7,087 fast-gate eligible
1,161 hard fail
```

8,248 条中已知阳性 CDR identity 最大值为 `68.75%`，低于比赛 `80%` 线。

Teacher500 不是机械取模型 Top500，而是按下列层抽样：

```text
140 high prior
100 decision boundary
60 low-prior QC pass
120 diversity
80 uncertainty/disagreement
```

并保持 40 parents、3 patches、2 modes 和 parent-cluster 350/75/75 train/dev/test split。

Teacher500 完成：

```text
500/500 candidates
4,394/4,394 valid contact poses
0 contact failure
stable multi-pose G1/G2/G3/G5 = 13/339/135/13
```

V3-P1 使用：

- frozen V2.3 residue/contact backbone；
- mean-pooled v3_full generic prior；
- PVRIG residue embedding；
- 8X6B/9E6Y fixed structure features；
- hotspot/interface mask；
- trainable contact adapter、ordinal G1-G5 head、8 个 geometry regressors、contact/site head 和 small fusion ranker；
- ordinal `1.0` + geometry `0.7` + contact `0.5` + paratope/epitope `0.25/0.25` + rank `0.5` + replay `0.3` 损失。

模型在 unseen-parent formal test 上的 NDCG 和 Spearman 很高，但将 hotspot 乱序、移除 antigen 或置换 target 后 EF 完全不降。这是最重要的失败：模型学到了某种 teacher 排序信号，但没有证明这个信号来自 PVRIG 条件。

产物：

- `experiments/phase2_5080_v1/reports/PVRIG_V3_G_V3_P_EXECUTION_PLAN_AND_STATUS_ZH.md`
- `experiments/phase2_5080_v1/audits/pvrig_formal_teacher500_audit.json`
- `experiments/phase2_5080_v1/audits/phase2_v3_p1_formal_outcome_interpretation.json`

### 5.6 Docking Gold V1.3：工程闭包，标签稳定性未过

V1.3 将 47 cases 的 8X6B 和 9E6Y 真正分别进行 native docking，不再只对同一批 8X6B pose 做 9E6Y overlay score。

最终执行：

```text
47 cases
94 native receptor runs
752 Top-8 poses
30/30 new runs PASS
processor/calibration primary-rebuild byte-identical
```

校准：

```text
LOFO macro G1-G3 recall = 0.9333
receptor consistency >=0.70 = 11/11
modal tier probability >=0.70 = 6/11 (required >=9/11)
```

所以唯一正确结论是：

```text
Docking execution: PASS
Development method: FAIL
Docking Gold release: false
Training label release: false
P2 training ready: false
```

这不是 docking 命令失败，而是证明了离散 tier 对 bootstrap/pose 重采样过于敏感。

产物：

- `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_3_EXECUTION_STATUS_ZH.md`

## 6. 测试和质量控制回顾

本项目有两种测试，不能混淆：

### 6.1 工程测试

已经验证：

- 数据和 manifest 数量闭包；
- exact sequence/cluster/PDB 泄漏防护；
- checkpoint 和 embedding cache 哈希；
- remote controller 单写者、断点续跑和迁移；
- Top-8 禁止 backfill；
- chain/ATOM/OXT/HETATM 坐标 identity；
- selector/processor/calibrator 双构建字节一致；
- formal unseal 和阈值不可事后修改；
- fail-closed release semantics。

V1.3 最终相关回归为 `65/65 PASS`，并经两条独立 verifier 复核无差异。

### 6.2 科学验收门

工程测试 PASS 不等于模型或标签科学有效。我们使用了：

- sealed formal test；
- multi-seed consistency；
- cluster bootstrap CI；
- paired permutation；
- exact random baseline；
- VHH-only / antigen ablation / target permutation / hotspot shuffle；
- label shuffle；
- generic contact/paratope replay retention；
- positive-family LOFO；
- receptor consistency；
- modal-tier bootstrap stability。

这些门的价值正在于：它们阻止了我们将“能跑”、“dev 指标好看”或“某个 pose 遮挡很强”错写为已验证的 binder/blocker 真值。

## 7. 当前候选库真实状态

### 7.1 已具备

```text
8,640 raw target-conditioned designs
8,248 exact-unique designs
7,087 fast-gate eligible designs
40 parent framework clusters
3 PVRIG target patches
2 design modes
500 complete Teacher candidates
4,394 valid poses
```

Teacher500 的 352 条 provisional stable G1+G2 候选覆盖全部 40 个 parent：

```text
A_CENTER = 115
B_LOWER  = 121
C_CROSS  = 116
H3       = 169
H1H3     = 183
```

因此当前已经不缺基础设计数量，也不缺 parent/patch/mode 多样性。

### 7.2 仍缺少

Teacher500 manifest 的 500 条全部为：

```text
submission_eligible=false_teacher_data_only_pending_separate_full_qc
independent_9e6y_docking=false
```

这表示它们：

- 已通过 fast gate；
- 已有单体和 8X6B docking + 9E6Y overlay teacher；
- 但还没有经过面向参赛的独立 full QC release；
- 也没有 candidate-specific 独立 9E6Y native docking；
- 还没有实验 expression/BLI/purity/Kd/IC50 真值。

因此当前不能标记为 `SUBMISSION_READY`，但已经可以直接进入最终组合选择，不必重新生成一轮基础候选库。

## 8. 我们遇到的主要问题和真正教训

### 8.1 模型大不等于排序好

V2.2 的 contact 很好，但 pair 只略高于随机；V2.4 加 listwise 后仍没改善；V3-G2 增加 residue 交互后反而输给 mean-pool。真正的瓶颈是 label 与 split，不是网络层数。

### 8.2 dev 胜利不等于 formal 胜利

初代 V3 在 dev 上领先，但 sealed external block 上明显落后。这说明不能用 dev 调参后的最好结果代替预注册 formal 结论。

### 8.3 能预测 teacher 不等于使用了 target

V3-P1 有高 NDCG，但去掉 antigen 或打乱 hotspot 后排序几乎不变。它可能在识别 parent/framework/generator style，而不是 PVRIG 局部界面。

### 8.4 一个很好的 pose 不等于稳定几何

V1.3 的 receptor consistency 是 11/11，但 modal tier 只有 6/11 稳定。这说明候选的几何证据必须看 top-k、cluster、continuous metrics 和重复稳定性，不能只看 rank-1 或单一 G1/G2 类别。

### 8.5 科学方法冻结和比赛交付必须分线

V3-P1 和 V1.3 的 FAIL 必须保留，但这不意味着不能用其计算产物做谨慎的候选优先级。比赛中可以使用不完美的代理信号，但必须：

- 降低权重；
- 不伪装成实验概率；
- 保留 exploration quota；
- 用多样性和人工复核对冲偏差。

## 9. 比赛优先的下一步

### P0：立即冻结研究失败结论

```text
V3-P1 deployment = no
Docking Gold V1.3 release = no
P2 training = blocked
```

不修改已解封 test，不降低 V1.3 门槛，不在比赛截止前强行训 V3-P2。

### P1：对 Teacher500 全量运行比赛 full QC

不使用 V3-P1 或 generic score 先截断这 500 条，而是对 500/500 运行：

- official validator；
- ANARCI/IMGT 完整性；
- official + local positive CDR novelty；
- AbNatiV；
- Sapiens/human-likeness；
- ProtParam；
- liability/PTM；
- expression/purity/developability risk；
- TNP 只补 Top100，不作全量硬门。

执行时应使用 `--full-qc-limit 0`，避免因弱模型排序导致 capacity truncation。full QC 结果必须按 `candidate_id` 回并 Teacher500 lineage，不能丢失 parent/patch/mode/CDR before-after/SHA256。

主输入：

- `experiments/phase2_5080_v1/data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_teacher_manifest_v1.csv`

退出条件：

```text
500/500 有 full-QC 决策行
0 lineage loss
0 candidate_id mismatch
hard fail 和 review 风险完整保留
```

### P2：形成 100-150 条 portfolio shortlist

选择原则：

```text
80%-85% exploitation:
  full QC 好
  binding/contact 弱先验一致
  provisional stable G1/G2 或连续几何较强

15%-20% exploration:
  full QC 好
  但模型低分/几何不确定
  parent/patch/mode/CDR3 明显不同
```

建议约束：

- 每个 parent 最多 3-4 条；
- 每个 parent + patch + mode 最多 1-2 条；
- 三个 patch 各自保留约 25%-40%；
- H3 与 H1H3 都要保留；
- diversity 是硬约束，不是一个 5% 加分项。

如果 Teacher500 full-QC hard-pass 少于 80，再从剩余 6,587 条 fast-gate eligible 序列中抽取 200 条高 QC/高多样性 reserve；否则不重新生成基础库。

### P3：对 shortlist 补独立结构和双受体证据

Teacher500 已有 NanoBodyBuilder2 单体，不必全量重跑。建议：

- Top100：IgFold 或 RF2 做 CDR3/整体折叠交叉检查；
- Top60-80：独立 9E6Y native docking；
- Top20：独立 8X6B + 9E6Y replicate/seed 复核；
- Top20：人工检查 PVRL2 遮挡、碰撞、CDR 参与和错误接触角。

可以复用 V1.3 已通过工程验证的执行链，但输出只能标为 competition computational evidence，不能叫 Docking Gold。

排序应优先使用：

- continuous hotspot/contact/occlusion metrics；
- top-k median；
- blocker-supporting cluster count；
- receptor consistency；
- best-pose vs median gap；
- repeat/seed stability；
- 人工 pose verdict。

不把 G1/G2/G3 作唯一硬门。

### P4：按比赛评分选 Top50 和 Top10

先做 hard gate，再做 Pareto/portfolio，最后才在层内给 operational score。

建议的比赛 operational score（非校准概率）：

```text
40% binding/contact evidence
25% expression/purity/developability
20% independent geometry robustness
10% monomer structure confidence
 5% novelty
```

由于 V1.3 标签稳定性失败，geometry 权重不应继续高于 binding 和 developability。多样性仍使用硬约束，不并入这个分数。

Top10 至少应满足：

- >=5 个 CDR3/全序列 cluster；
- >=4 个 parent/scaffold/angle 家族；
- 同一近邻家族最多 2 条；
- 三个 PVRIG patch 均有代表；
- 至少 2 条强 expression/purity 对冲候选；
- 至少 2 条 alternative angle；
- 最多 1 条 high-risk/high-reward exploration。

### P5：提交包与排名并行准备

不要等 Top50 完全冻结后才开始：

- `submission_top50.fasta`；
- `submission_top50_ranked.csv`；
- `submission_top50_lineage.csv`；
- Top10 structure/pose dossier；
- 1 页方案摘要；
- 模型/工具/权重开源归属；
- 输入和输出 SHA256；
- clean-directory replay 脚本与验证收据。

## 10. 截止日前的建议日程

| 日期 | 主任务 | 退出条件 |
| --- | --- | --- |
| 7/15-7/16 | Teacher500 全量 full QC；冻结 candidate/full-QC merge | 500/500 有决策与 lineage |
| 7/16-7/17 | 选 100-150 条 portfolio shortlist；Top100 TNP/交叉单体 | 配额与 exploration 闭包 |
| 7/17-7/21 | Top60-80 independent 9E6Y；Top20 dual-receptor replicate | 连续几何和稳定性表完成 |
| 7/20-7/22 | 人工 pose 复核；多轴 Pareto；Top50/Top10 草案 | Top10 多家族、无硬失败 |
| 7/22-7/24 | 冻结 Top50；生成官方模板、1 页摘要和 dossier | `SUBMISSION_CANDIDATE_RELEASE` |
| 7/24-7/25 | 独立 clean replay、格式和 SHA 审计 | 数量/顺序/哈希完全一致 |
| 7/26 | 仅做上传、平台格式和回执；内部截止建议 16:00 | 保存成功回执 |

### 当前计算资源快照

2026-07-15 只读检查：

```text
Node1: SSH OK, load1 ~2.0, 8 x RTX 4090 基本空闲, /data 剩余约 20 TB
Node23: SSH OK, load1 ~27.5, 可作受控 CPU overflow
Node25: 当前 SSH alias 不可解析，不纳入关键路径
```

因此 full QC 和 Top100 单体交叉检查应立即使用 Node1，不需要继续等待计算资源。

## 11. 如果能做快速实验，它的优先级高于再训一版模型

当前最大不确定性是真实 binding/expression，而不是计算分数小数点后两位。

如果实验周转允许，应从 full-QC 后的设计候选中选 24-48 条小面板，优先获取表达/纯度和单浓度 BLI。这批应是新的设计候选面板，不是将旧 V2.5 24 条 control/public panel 直接当成提交序列。

即使只有少量实验结果，也比在同一批已解封 docking labels 上继续调参更能提高比赛成功率。

## 12. 比赛之后的模型研究路线

### 12.1 V3-P2 新版本

必须使用新的 untouched holdout，不能在已解封的 P1 formal 75 条上继续调参。

新数据应包含：

- 300-500 条 active-learning teacher；
- 新 parent clusters；
- 多种 generation methods，不再只有 RFantibody；
- fixed-pose AntiFold/ProteinMPNN redesign；
- conservative CDR redesign；
- 候选级独立 9E6Y docking；
- 新的 parent/method holdout。

模型必须先在 dev 上通过：

- hotspot shuffle 显著降低；
- antigen ablation 显著降低；
- target permutation 显著降低；
- VHH-only 显著差于 full model；
- contact/paratope replay 三 seed 保留 >=90%。

### 12.2 Docking Gold 新方法版本

不应只把 V1.3 的 `0.70` 阈值改低。新预注册应研究：

- continuous `R_gold` 或 soft tier distribution；
- 多 seed/multi-pose 后验而不是只取 modal class；
- best-pose 与 median 差距；
- receptor-specific uncertainty；
- 新的独立 positive families；
- 与实验 binding/nonblocking/nonbinding 标签的对齐。

当前 47-case 可继续作 development，但不能在看过 V1.3 后同时调整规则并仍将其称为 pristine formal test。

### 12.3 真实实验标签

长期价值最高的不是更大模型，而是：

- 新设计候选的 expression/purity；
- 真实 PVRIG binder/nonbinder；
- binder-but-nonblocker；
- competition/IC50；
- 新独立 positive families。

这些数据才能将 generic binding、docking geometry 和 experimental blocking 三条证据线真正连起来。

## 13. 最终决策

### 当前要做

```text
1. Teacher500 full QC
2. 100-150 portfolio shortlist
3. independent 9E6Y / Top20 replicate
4. Top50/Top10 portfolio freeze
5. submission package and clean replay
```

### 当前不做

```text
1. 不强行启动 P2 training
2. 不部署 V3-P1 主导排序
3. 不将 provisional G1-G5 写成实验真值
4. 不在已解封 test 上反复调参
5. 不重新生成一轮 8,000+ 基础库，除非 Teacher500 full-QC hard-pass <80
```

### 结束标准

只有同时满足以下条件，项目状态才能改为 `SUBMISSION_READY`：

1. 最终候选正好 50 条，ID/序列/顺序/SHA256 唯一；
2. 50/50 official validator、ANARCI/IMGT、CDR novelty 和 full hard gate 通过；
3. 50/50 有完整 design lineage；
4. 已知阳性、专利序列和 calibration mutants 与提交集完全隔离；
5. 50/50 有 developability/expression/purity risk 摘要；
6. Top10 有完整单体、candidate-specific 复合物、双受体证据和人工复核；
7. Top10 至少 5 个 cluster、4 个 parent/angle 家族，同家族最多 2 条；
8. 排序表分开 binding、geometry、structure、developability、expression/purity 和 diversity；
9. 官方模板、1 页摘要和 Top10 dossier 完成；
10. 在干净目录重放后，数量、顺序和 SHA256 完全一致。

## 14. 关键证据索引

- 比赛目标：`node1/PVRIG_COMPETITION_ASSET_AND_GOAL_AUDIT_20260712.md`
- V2.2：`experiments/phase2_5080_v1/reports/phase2_v2_2_full2277_eval.md`
- V2.3：`experiments/phase2_5080_v1/reports/PHASE2_V2_3_STRICT_EVALUATION_V1.md`
- V2.4：`experiments/phase2_5080_v1/reports/PHASE2_V2_4_STRICT_EVALUATION_V1.md`
- V2.5：`experiments/phase2_5080_v1/reports/PHASE2_V2_5_STRICT_EVALUATION_V1.md`
- V3 架构：`experiments/phase2_5080_v1/reports/PHASE2_V3_ARCHITECTURE_PLAN.md`
- V3-G2：`experiments/phase2_5080_v1/runs/phase2_v3_g2_final_evaluation_v1/final_evaluation_summary.json`
- Teacher500/V3-P1：`experiments/phase2_5080_v1/reports/PVRIG_V3_G_V3_P_EXECUTION_PLAN_AND_STATUS_ZH.md`
- Teacher500 audit：`experiments/phase2_5080_v1/audits/pvrig_formal_teacher500_audit.json`
- V3-P1 解释：`experiments/phase2_5080_v1/audits/phase2_v3_p1_formal_outcome_interpretation.json`
- V1.3 终态：`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_3_EXECUTION_STATUS_ZH.md`
- Teacher500 manifest：`experiments/phase2_5080_v1/data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_teacher_manifest_v1.csv`
- Teacher500 candidate summary：`experiments/phase2_5080_v1/prepared/pvrig_teacher_formal_v1/candidate_summary.csv`
