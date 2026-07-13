# PVRIG V3-G / V3-P 执行规划与当前状态

更新时间：2026-07-13 16:40（Asia/Shanghai）

> 最新状态：Teacher500 docking、双参考 geometry/contact teacher、V3-P full + label-shuffle 三种子训练和 evaluator-only formal test 已全部完成。冻结结论为 `FAIL_V3_P1_FORMAL_SURROGATE_GATE`；这是完整执行后的科学门失败，不是 pipeline 未跑完。

## 一、当前结论

**是的，当前必须先开始生成用于 V3-P 微调监督的 PVRIG docking teacher 数据。**

原因不是 docking 标签等同于真实阻断，而是：

1. V3-P 的监督目标是 PVRIG 界面几何、遮挡层级和 pose 稳定性；没有 Node1 teacher，V3-P 没有可训练的靶点专用标签。
2. 通用 V3-G 只能学习 VHH 如何识别抗原，不能凭通用 binder 标签推出 PVRIG-PVRL2 阻断几何。
3. docking teacher 生成是当前耗时最长的路径，应尽早启动；但不需要等待它全部完成后才处理 V3-G。正确方式是两条路径并行，最终在 V3-P 汇合。

当前实际执行顺序为：

```text
路径 A：PVRIG 候选生成 -> 分层抽样 -> Node1 docking teacher
路径 B：cluster-safe 通用数据 -> mean-pool 基线 -> residue-level V3-G
                         路径 A + 路径 B
                                  ↓
                     V3-P PVRIG geometry surrogate
```

## 二、证据边界

全流程必须保持以下证据分离：

| 证据 | 能说明什么 | 不能说明什么 |
| --- | --- | --- |
| 通用真实 binder/non-binder | 通用结合先验 | PVRIG 结合、亲和力或阻断 |
| 结构 contact/site | paratope、epitope、残基接触能力 | 真实功能阻断 |
| Node1 docking teacher | 计算几何、遮挡和 pose 稳定性代理 | 实验结合或实验阻断真值 |
| 已知 PVRIG 阳性 | 阈值、机制和校准 anchor | 普通训练正样本或候选来源 |
| 最终实验 | BLI、表达、纯度和功能 | 才是提交决策的最高证据 |

已知 PVRIG 阳性及其衍生突变继续保持 `calibration-only / leakage-excluded`；CDR 阳性相似度仅用于模型外 hard gate，不作为模型输入。

## 三、PVRIG docking teacher 路径

### 3.1 Parent40 已冻结

正式父序列清单：

```text
experiments/phase2_5080_v1/data_splits/pvrig_teacher_formal_v1/parent40_manifest.tsv
```

审计结果：

```text
40 个 parent framework cluster
train/dev/test parent clusters = 28/6/6
4 个 CDR3 长度区间，各 10 条
known-positive exact overlap = 0
max positive CDR identity <75%
```

### 3.2 RFantibody 正式候选库已完成

设计规模：

```text
40 parents
× 3 PVRIG patches
× 2 design modes（H3 / H1H3）
× 12 RFdiffusion backbones
× 3 ProteinMPNN sequences
= 8,640 raw candidates
```

Node1 根目录：

```text
/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/rfantibody_generation
```

预验证已经通过：

```text
8/8 validation tasks complete
0 failed
覆盖 H3 最长 20 aa 和 H1+H3
```

正式生产已经启动，主 worker、反向尾部 worker 和可恢复 boost worker 在 GPU 1-7 上并行，每个 task 均使用文件锁防止重复写入。`boost_v1 + boost_v2` 启动后未见 OOM、Traceback 或 failed marker。截至 `2026-07-13 02:03 +08:00`：

```text
35/240 task complete
0 failed
529/2,880 backbone PDB 已生成
1,260/8,640 ProteinMPNN sequence PDB 已生成
37 个 generation worker 仍在运行
```

节点当时只有 64 个 CPU 核，而每个默认 RFdiffusion 进程会创建约 100 个 CPU 线程，实测 CPU pressure 约为 95%。因此没有继续盲目增加 worker，而是对后续新启动的 task 设置可覆盖的 `OMP/MKL/OpenBLAS/NumExpr=1`；这不改变 GPU、seed、hotspot、loop 或生成参数。

首次施加该运行时参数时曾原地改写正在被 Bash 读取的 `run_task.sh`，导致 7 个已完成 RFdiffusion 的 task 在进入 ProteinMPNN 时以 `rc=127` 退出。这 7 个 task 的 84 个 backbone 全部保留，没有 `failed.json`，也没有删除任何输出。随后启动了覆盖所有 205 个未完成 task 的受锁 recovery worker：七个异常 task 已全部恢复为 `complete`，每个均有 `12 backbone + 36 sequence PDB`。运行脚本不再在存活 task 期间修改；原脚本、当前脚本和 recovery plan 的哈希/审计文件均保存在 Node1 生产目录。恢复后快照为 `42/240 complete、0 failed marker、682 backbone、1,512 sequence PDB`。

所有旧的 100-thread RFdiffusion 进程退出后，新进程均为 `OMP=1`、每进程 5–6 threads，CPU pressure 从约 95% 降至约 27%。在 GPU 利用率与显存允许的范围内将 worker 平衡到 20 个后，`2026-07-13 03:03–03:23 +08:00` 从 `68` 增至 `89/240 complete`，稳态吞吐约为 60 task/小时，仍为 `0 failed marker`、无 failed status。

本地轻量审计证据：

```text
experiments/phase2_5080_v1/audits/pvrig_formal_generation_recovery_plan_20260713.json
experiments/phase2_5080_v1/audits/pvrig_formal_generation_run_task_sha256_20260713.tsv
experiments/phase2_5080_v1/audits/pvrig_formal_generation_balanced_boost_plan_20260713.json
experiments/phase2_5080_v1/logs/pvrig_formal_teacher_pipeline_full_unittest_20260713T0304.log
```

完整本地回归为 `255 tests / 9.115s / OK`。

最终生成门已于 `2026-07-13 06:02 +08:00` 通过：

```text
240/240 task complete
0 failed marker
2,880/2,880 backbone PDB
8,640/8,640 ProteinMPNN sequence PDB
```

自动接管控制器已改为独立 session 运行，对瞬时 SSH 错误和非法返回格式会重试，不会因一次轮询失败而丢失 `240/240` 后的最终化接管：

```text
experiments/phase2_5080_v1/src/start_pvrig_formal_teacher_pipeline_controller.sh
experiments/phase2_5080_v1/src/monitor_pvrig_formal_teacher_pipeline.sh
experiments/phase2_5080_v1/logs/pvrig_formal_teacher_pipeline_controller.log
```

### 3.3 正式候选收集已通过

脚本：

```text
experiments/phase2_5080_v1/src/collect_pvrig_formal_rfantibody_candidates.py
```

它从 RFantibody 输出 PDB 的 H chain 直接重建完整 VHH，并保留：

```text
parent_id / parent_sequence
parent framework cluster / formal split
patch / hotspots / design mode
backbone index / ProteinMPNN index
CDR1/2/3 before and after
source PDB and SHA256
```

收集器已对 21 个完成 task 重跑部分验证：

```text
756 raw records
709 exact-unique sequences
47 exact duplicate records
4 个 parent 已覆盖
0 framework/CDR/provenance parse error
```

这组 partial 数据只用于预验证。`240/240` 后已重跑正式收集，结果为：

```text
status = PASS_COMPLETE_COLLECTION
raw records = 8,640
exact-unique sequences = 8,248
exact duplicate records = 392
parent = 40
patch = 2,880 / 2,880 / 2,880
mode = 4,320 H3 / 4,320 H1H3
formal split = 6,048 train / 1,296 dev / 1,296 test
```

同一 partial 集的 fast gate 集成验证：

```text
FORMAL_ELIGIBLE = 603 / 709（85.0%）
HARD_FAIL       = 106 / 709

主要失败：
CDR N-linked glyco motif = 101
CDR homopolymer >=5      = 7
```

这一结果说明生成库的大多数序列可进入模型前筛，但不能取消正式全库 fast gate。

正式全库 fast gate 也已完成：

```text
input exact-unique = 8,248
FORMAL_ELIGIBLE = 7,087
HARD_FAIL = 1,161

hard failure counts:
CDR N-linked glyco motif = 1,147
CDR homopolymer >=5 = 17
```

### 3.4 正式 teacher 不是全 8,640 条 docking

完整生成后执行：

```text
8,640 raw
-> exact dedup
-> sequence / CDR / framework hard gate
-> V3-G generic prior + cheap QC
-> 分层抽取约 500 条 prospective teacher
```

500 条建议配额：

| 抽样层 | 数量 | 目的 |
| --- | ---: | --- |
| 高 generic contact/binding prior | 140 | 提高成功候选密度 |
| 决策边界 | 100 | 学习排序边界 |
| 低分但 QC 通过 | 60 | 学习真实计算失败模式 |
| parent/patch/method/embedding 多样性 | 120 | 覆盖搜索空间 |
| 模型冲突或高不确定性 | 80 | 支持主动学习 |

约束：

```text
同一 parent 常规配额 <=10，绝对上限 <=13
同一 parent + patch + mode <= 3-4
train/dev/test 沿用 Parent40 的 28/6/6，不按候选行随机拆分
```

这里必须修正原规划中的一个算术冲突：40 个 parent 若硬性限制每个最多 10 条，最多只能得到 400 条，不可能抽到 500 条。正式 500 配额按 `350/75/75` 分配到 train/dev/test，平均每个 parent 为 12.5 条，因此绝对上限设为 13；其中常规高分配额仍优先不超过 10，额外 100 条只用于边界、多样性和不确定性层。

目前已有可执行实现：

```text
fast_gate_pvrig_formal_candidates.py
prepare_pvrig_formal_candidate_meanpool_inputs.py
score_pvrig_formal_candidates_meanpool.py
select_pvrig_formal_teacher500.py
build_pvrig_formal_teacher500_package.py
run_pvrig_formal_teacher500_finalize.sh
```

21-task partial 数据已完成真实 VHHBERT/ESM2 embedding 和三种子 `v3_full` 评分集成测试：`603/603` 条序列成功输出 generic prior、seed uncertainty、rank disagreement 和 cheap QC score。不使用 hash embedding 冒充正式分数。

该 partial 集还显示 mean-pooled 高分明显被 parent framework 主导：前 10 全部来自同一 parent。这正是 Teacher500 不能机械取 Top 500、必须实施 parent/patch/mode 配额和 40% 左右非高分抽样的实证。

正式评分和 Teacher500 冻结已完成：

```text
scored eligible candidates = 7,087
Teacher500 unique candidates/sequences = 500 / 500
selection layers = 140 high prior + 100 boundary + 60 low-prior QC
                 + 120 diversity + 80 uncertainty/disagreement
split = 350 train / 75 dev / 75 test
parent coverage = 40，每个 12–13 条
parent + patch + mode max = 3
patch = 164 / 167 / 169
mode = 254 H1H3 / 246 H3
manifest SHA256 = 9285dd09db2ca1492fa97d52e7d009f4891777548adf06bc1845935aceeb0991
```

七分片包为 `72/72/72/71/71/71/71`，总计 500 条；本地和 Node1 哈希校验已返回 `PASS_TEACHER500_REMOTE_PACKAGE_VERIFIED`。

### 3.5 正式 Node1 teacher 字段

每条候选执行：

```text
VHH 单体结构
-> HADDOCK top poses
-> 8X6B 几何评分
-> 9E6Y 参考界面重评分
-> residue-pair contact frequency
-> top-k pose/cluster 稳定性
```

必须输出：

```text
8X6B / 9E6Y per-pose metrics
G1-G5 ordinal tier
top10_AA_fraction
top10_A_or_B_fraction
blocker_supporting_cluster_count
median_hotspot_overlap
median_total_occlusion
pose_cluster_entropy
best_pose_vs_median_gap
PVRIG-specific contact-frequency matrix
```

不能使用 `A/A=1、其他=0`，也不能只学习 rank-1 pose。9E6Y 重评分仍不等于独立 9E6Y docking；该限制必须写入 teacher manifest。

### 3.6 Teacher500 Node1 执行状态

正式七分片 controller 已于 `2026-07-13 06:07 +08:00` 启动。单体阶段于 `06:31:37` 通过：

```text
NanoBodyBuilder2 raw PDB = 500
normalized chain-A PDB = 500
sequence validation JSON = 500
monomer geometry QC JSON = 500
refinement failure -> unrefined fallback = 16
fallback success / failure = 16 / 0
nonzero normalize/sequence/geometry QC = 0
monomer.complete = present
```

HADDOCK 于 `06:31:37` 启动。首轮实测每条约 4.3–4.8 分钟，但原设置的 300 秒 load-gate 轮询会在每条之间增加约 5 分钟空等。在 14 条 docking 已成功、七个 shard 都处于 `LOAD_GATE_WAIT`、且确认无活动 HADDOCK 进程的安全窗口，仅将轮询间隔从 300 秒改为 60 秒并以 `docking` resume 模式重启。阈值仍为 load1 48，HADDOCK 参数、每分片核数和所有输入均未改变；已完成 14 条由 `HADDOCK_SKIP_COMPLETE` 验证后跳过。

本地独立后处理监控器已启动，只在同时满足 `docking.complete + 500 success + 0 fail` 时才运行 8X6B/9E6Y、contact-frequency 和 formal Teacher500 audit：

```text
experiments/phase2_5080_v1/src/monitor_pvrig_formal_teacher500_docking.sh
experiments/phase2_5080_v1/src/start_pvrig_formal_teacher500_docking_monitor.sh
experiments/phase2_5080_v1/logs/pvrig_formal_teacher500_docking_monitor.log
```

该监控器已通过“瞬时 SSH 失败后重试”和“500/500 完成后触发 mock postprocess”两类合约测试。

## 四、V3-G 通用模型路径

### 4.1 Cluster-safe 数据已完成

正式数据脚本：

```text
experiments/phase2_5080_v1/src/prepare_phase2_v3_g2_cluster_safe_data.py
```

数据目录：

```text
experiments/phase2_5080_v1/prepared/phase2_v3_g2/
```

使用 MMseqs2：

```text
VHH identity >=85%
coverage >=80%
cov-mode = 0
```

并将与 sealed external hTNFa 同 cluster 的开发序列整簇排除。最终审计：

```text
138,926 real assay pairs
60,316 unique VHH
18,444 VHH clusters
train/dev/test rows = 111,206 / 13,933 / 13,787
train/dev/test VHH = 48,122 / 6,099 / 6,095
exact pair overlap = 0
exact VHH overlap = 0
MMseqs cluster overlap = 0
所有 target × label × split 均有覆盖
```

为保护 external hTNFa：

```text
排除 18,581 development rows
对应 7,833 unique VHH
retained external cluster overlap = 0
```

审计文件：

```text
experiments/phase2_5080_v1/prepared/phase2_v3_g2/prepare_audit_v1.json
```

### 4.2 Residue cache 和 CDR masks 已完成

```text
ESM2-8M residue cache：65,922 sequences，141 shards，约 4.1 GB
CDR mask manifest：62,833 VHH
exact annotation：511
motif heuristic：56,044
unresolved：6,278
```

未解析 CDR 不被伪造为负标签；训练器保留其完整序列表征并单独报告 unresolved 行数。

### 4.3 Mean-pooled 基线已重跑

同一 cluster-safe split 上，development 选择出的最强基线是 `v3_full`：

```text
dev macro target AP = 0.3951
test macro target AP = 0.3415
test overall AP = 0.4813
```

因此 residue-level V3-G 不能只证明“能运行”，而必须在冻结门下显著超过这一基线。

基线结果：

```text
experiments/phase2_5080_v1/runs/phase2_v3_g2_meanpool_baselines/
```

### 4.4 Residue-level V3-G2 已进入正式训练

训练脚本：

```text
experiments/phase2_5080_v1/src/train_phase2_v3_g2_generic.py
```

训练目标：

```text
真实 binder/non-binder BCE
+ 跨抗原家族低权重 contrast
+ 同一 VHH 的真实 target label contrast
+ contact/site replay
```

语言模型和 residue embedding 冻结；训练 cross-attention、contact/site replay 层和 pair head。4-batch smoke 已通过，并实际触发 binding、target contrast 和 replay 三条损失。

正式预注册：

```text
experiments/phase2_5080_v1/audits/phase2_v3_g2_preregistration.json
```

冻结 seeds：

```text
83 / 89 / 97
```

主要门：

```text
三种子 ensemble test macro target AP > 最强 mean-pooled baseline
至少 2/3 seeds 单独超过 baseline
ensemble delta bootstrap 95% CI lower bound > 0
observed target-contrast win rate >= 0.55
contact/paratope replay 指标保留源 checkpoint 的至少 90%
label-shuffle / target-shuffle 不得通过主门
```

Seed 83、89、97 和三种子正式判定已完成：

| seed | best epoch | dev macro target AP | test macro target AP | test overall AP |
| ---: | ---: | ---: | ---: | ---: |
| 83 | 2 | 0.2649 | 0.2342 | 0.3094 |
| 89 | 2 | 0.2660 | 0.2501 | 0.3306 |
| 97 | 3 | 0.2378 | 0.2478 | 0.3701 |
| mean-pooled `v3_full` baseline | - | 0.3951 | 0.3415 | 0.4813 |

三种子 ensemble 的正式结果：

```text
internal cluster-safe test macro target AP = 0.244264
mean-pooled v3_full baseline               = 0.341462
observed delta                            = -0.097197
VHH-cluster bootstrap 95% CI              = [-0.180220, -0.038091]

target-dependence positive true-swap margin = +0.354730
observed target contrast win rate            = 0.622222
contact replay retention                      = 97.47%
paratope replay retention                     = 96.97%
```

因此正式结论是：

```text
FAIL_FALLBACK_TO_MEANPOOL_V3_FULL
```

这不是说 residue backbone 没有价值。它的 target-dependence 和 contact/site 保持都通过，但它不能取代 mean-pooled `v3_full` 成为当前 generic binding ranker。后续 V3-P 使用：

```text
V2.3 frozen residue/contact backbone
+ mean-pooled v3_full generic binding prior
+ PVRIG docking/contact-frequency teacher
```

不使用本次失败的 V3-G2 pair head 直接主导 Teacher500 或最终提交排序。

正式判定器：

```text
experiments/phase2_5080_v1/src/evaluate_phase2_v3_g2_final.py
```

external hTNFa 已准备 `5,571` 条、其中 `677` binder，与保留开发集 exact VHH overlap 为 `0`。描述性比较中，residue ensemble AP 为 `0.222219`，高于 mean-pooled baseline 的 `0.130610`。但它在旧 V3 中已经解封，因此只能证明这一特定 transfer block 上有信号，不能推翻主 cluster-safe test 的失败，也不能冒充新的 pristine formal test。

正式产物：

```text
experiments/phase2_5080_v1/runs/phase2_v3_g2_final_evaluation_v1/final_evaluation_summary.json
experiments/phase2_5080_v1/runs/phase2_v3_g2_final_evaluation_v1/PHASE2_V3_G2_FINAL_EVALUATION_ZH.md
```

## 五、V3-P 训练顺序

V3-P 必须等首批正式 Node1 teacher 标签可用后训练：

```text
V3-G frozen residue representation
+ PVRIG 8X6B/9E6Y fixed features
+ Node1 per-pose/contact-frequency teacher
-> ordinal G1-G5 head
-> continuous geometry heads
-> within-parent/campaign rank loss
-> ensemble uncertainty
```

第一轮：

```text
约 500 条 teacher
冻结 ESM2/VHHBERT
低学习率训练 PVRIG cross-attention/pooling
+ ordinal MLP 或 LambdaMART
```

第二轮主动学习：

```text
高分
高不确定性
seed disagreement
binding prior 与 geometry surrogate 冲突
新 parent / patch / method
```

再增加 300-500 条 teacher，目标总量约 800-1,000 条。

## 六、Teacher500 与 V3-P 已完成正式闭包

### 6.1 Docking teacher 最终规模

Node1 与 5080 审计分流后的最终闭包为：

```text
Teacher candidates = 500 / 500
HADDOCK selected poses = 4,394
valid contact poses = 4,394
failed contact poses = 0
parent framework clusters = 40
train / dev / formal test = 350 / 75 / 75
status = PASS_FORMAL_TEACHER500_READY
```

pose 级几何分布：

| consensus class | pose 数 |
| --- | ---: |
| `CONSENSUS_BLOCKER_LIKE_A` | 138 |
| `SINGLE_BASELINE_BLOCKER_RECHECK` | 1,991 |
| `BLOCKER_PLAUSIBLE_B` | 1,941 |
| `EVIDENCE_INFERENCE_ONLY_E` | 324 |

candidate 级分布：

| 口径 | G1 | G2 | G3 | G5 |
| --- | ---: | ---: | ---: | ---: |
| best observed evidence | 92 | 357 | 50 | 1 |
| stable multi-pose geometry | 13 | 339 | 135 | 13 |

5080 分流和失败恢复没有更改 docking 科学配置：

```text
shard 2-5 offload = 285 candidates / 2,520 selected models
tail offload = 24 candidates / 226 selected models
3 个 Node1 CNS 输出丢失候选在 5080 默认配置下重跑成功
tolerance relaxation used = false
HADDOCK3 = 2025.11.0
CNS SHA256 = ce6b0c6b9d38e09991fb15431402e92cb38c723544b2dcca7a8dc28b66643927
```

原 Node1 目录和竞态冲突记录都已保留，汇总审计为：

```text
experiments/phase2_5080_v1/audits/pvrig_teacher500_5080_offload_audit.json
experiments/phase2_5080_v1/audits/pvrig_formal_teacher500_sync_audit.json
experiments/phase2_5080_v1/audits/pvrig_formal_teacher500_postprocess_audit.json
experiments/phase2_5080_v1/audits/pvrig_formal_teacher500_audit.json
```

### 6.2 正式数据已封存

```text
status = PASS_PHASE2_V3_P1_FORMAL_DATA_SEALED
parent-cluster cross-split overlap = 0
sequence hash closure = true
train / dev / sealed test = 350 / 75 / 75
```

Teacher 主输出 SHA256：

```text
candidate_summary.csv = 14a75493825c826dc6e75f3c4471291d06bf0294b5778cc51e72d64898680270
pose_summary.csv = 08a58ed0da194b90589ed529fb3de653eb751b5c5dbebf8fdc9a71c435d88216
pose_contact_frequency.jsonl = f66be3f5d9bc5a31afc5689154da09462c12171501513de9f243c7a91b24f3a9
teacher manifest = 7ac150eb759f8ad51b0877cdbe651ede0818d5ed29ccc72fe1c37867093bbfcd
```

### 6.3 Full/null 三种子与 evaluator-only unseal 已完成

系统 Python 在启动时已漂移到 `torch 2.13.0+cpu`，因而第一个运行在任何 checkpoint 产生前 fail closed。后续建立了独立 venv，恢复与旧审计一致的：

```text
torch = 2.13.0+cu130
CUDA = 13.0
GPU = NVIDIA GeForce RTX 5080
successful run = formal_20260713T161346
```

环境恢复证据：

```text
experiments/phase2_5080_v1/audits/phase2_v3_p1_cuda_environment_recovery.json
```

正式产物哈希：

```text
full training summary = d1ffc6936f1c887fbae603e8a7be05fa71915993f6a03ef90db78ba7befd33da
label-shuffle summary = 40de25a653a5926c28b9e5ccc92b5e2c18d0c1668ec450206ea3b8e290d1e51f
artifact manifest = dd34bc999f1a43ae20d3fc40af7b09d827b6a4055c937ffb959373aaad9b1167
formal evaluation = 03788cac0e9f154870b168334db1eda5927f88540cd8992f2b49a2385cad549b
pipeline summary = 7851b3e9e9e8375ab8fb0c9572e10faeedc56fa4b18aa2b7c174d0d72fc777ad
```

## 七、V3-P1 正式结果

冻结结论：

```text
FAIL_V3_P1_FORMAL_SURROGATE_GATE
```

该 FAIL 必须保留，不能在看过 formal test 后修改阈值并仍称为同一版本。

### 7.1 主指标

| 指标 | 冻结门槛 | formal test | 结果 |
| --- | ---: | ---: | --- |
| G1+G2 Recall@Top20% | >=0.70 | 0.2642 | FAIL |
| G1+G2 EF@Top10% | >=3.0 | 1.4151 | FAIL |
| relevance Spearman | >=0.35 | 0.5215 | PASS |
| ensemble NDCG@100 | > strongest baseline | 0.9877 vs 0.9209 | PASS |
| parent-cluster bootstrap CI lower | >0 | 0.0172 | PASS |
| paired parent-cluster permutation | p<0.05 | p=0.0725 | FAIL |
| all 3 seed NDCG > baseline | required | 3/3 | PASS |

其中两个早期富集门在封存 test 的实际阳性率下数学上不可达：

```text
formal test = 75 rows
G1+G2 = 53 rows (70.7%)
Top10% = 8 rows -> EF 理论上限 = 75/53 = 1.4151
Top20% = 15 rows -> Recall 理论上限 = 15/53 = 0.2830
```

当前 ensemble 在 Top 8 找到 8 个 G1+G2，已达 EF 理论上限；Top 15 找到 14 个，接近 recall 理论上限。这说明预注册的 `3x EF / 70% recall` 是按低阳性率候选库设想的，与实际 teacher 分布不兼容。但这只是对 FAIL 的解释，不能追溯改写冻结判定。

### 7.2 真正需要修正的失败

target controls 没有显示足够的 PVRIG 条件依赖：

| control | EF 相对下降 | 要求 | 结果 |
| --- | ---: | ---: | --- |
| hotspot shuffle | 0% | >=25% | FAIL |
| antigen ablation | 0% | >=25% | FAIL |
| target permutation | 0% | >=25% | FAIL |
| VHH-only | 12.5% | >=25% | FAIL |
| label shuffle | 25% | >=25% | PASS |

这表明模型确实学到了 teacher 排序信号，但大部分信号仍可能来自 VHH 序列、parent 和生成器先验，而不是 PVRIG hotspot/antigen 条件。

generic replay 也未全部通过：

```text
paratope AUPRC retention = 99.12% / 99.83% / 100.00%  -> 3/3 PASS
contact AUPRC retention  = 66.46% / 105.24% / 72.79% -> 1/3 PASS
```

因此即使排除两个不可达的富集门，V3-P1 仍然不能被接受为 PVRIG target-conditioned 生产前筛器。

详细解释审计：

```text
experiments/phase2_5080_v1/audits/phase2_v3_p1_formal_outcome_interpretation.json
```

## 八、接下来应该怎么做

### 8.1 冻结 V3-P1，不直接部署

```text
V3-P1 = formal training complete, formal gate failed
deployment = no
claim = docking geometry surrogate research signal only
```

当前 Node1 大规模前筛仍应使用：

```text
cheap sequence/QC gates
+ mean-pooled generic prior 仅作弱先验
+ parent/patch/method diversity
+ 10%-20% exploration quota
```

不应让 V3-P1 独占 full QC 名额。

### 8.2 V3-P2 只在 train/dev 上做诊断与改进

1. 强化 generic multi-antigen target-swap/contrastive replay，不只保持 frozen output。
2. 对 PVRIG hotspot mask 加入可验证的 counterfactual 排序损失。
3. 限制 VHH-only / parent / generator-style 捷径，在 dev 上先要求 target controls 显著下降。
4. 提高 generic contact replay 权重或冻结更多 contact adapter，直到三种子 retention 全部 >=90%。
5. Teacher500 只有一种 generation method，因此当前不能声称已完成 leave-method challenge。

### 8.3 新版本必须使用新的 untouched holdout

`formal_20260713T161346` 的 75 条 test 已经解封，后续只能用于描述性对比，不能继续调参后仍称 pristine formal test。

V3-P2 建议：

```text
新增 300-500 条 active-learning teacher
+ 新 parent framework clusters
+ 更多生成方法/局部 pose redesign
+ 对关键候选补独立 9E6Y docking
-> 重新冻结 train/dev/new formal test
```

新预注册指标应根据 dev 中的标签基率设置为数学可达，例如：

```text
Precision@fixed Node1 budget
Recall@budget / theoretical maximum recall
NDCG and relevance Spearman
target-control degradation
contact/paratope replay retention
parent-cluster bootstrap and permutation
```

## 九、当前停止条件与项目状态

本轮“生成 teacher -> 训练 V3-P1 -> formal evaluator”的停止条件已全部满足：

```text
RFantibody 240/240 complete
Teacher500 500/500 complete
4,394/4,394 contact poses valid
formal data sealed
full 3 seeds complete
label-shuffle 3 seeds complete
artifact bundle hash-bound
formal evaluator-only test unseal complete
```

项目当前状态应记为：

```text
V3_P1_TRAINING_COMPLETE_FORMAL_GATE_FAILED
```

这不等于候选 portfolio 或实验阻断分子已准备完成。下一个科学步骤是建立 V3-P2 的 target-dependence 修复和新 holdout，而不是在已解封的 P1 test 上追求一个表面 PASS。
