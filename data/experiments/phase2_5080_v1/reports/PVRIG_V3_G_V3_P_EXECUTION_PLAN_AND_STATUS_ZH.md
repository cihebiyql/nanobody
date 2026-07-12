# PVRIG V3-G / V3-P 执行规划与当前状态

更新时间：2026-07-13 01:27（Asia/Shanghai）

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

### 3.2 RFantibody 正式候选库正在生成

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

最终门仍是 `240/240 task、0 failed、2,880 backbone、8,640 raw sequence records`。不会因为 partial 计数正常就提前宣称生成完成。

自动接管控制器已改为独立 session 运行，对瞬时 SSH 错误和非法返回格式会重试，不会因一次轮询失败而丢失 `240/240` 后的最终化接管：

```text
experiments/phase2_5080_v1/src/start_pvrig_formal_teacher_pipeline_controller.sh
experiments/phase2_5080_v1/src/monitor_pvrig_formal_teacher_pipeline.sh
experiments/phase2_5080_v1/logs/pvrig_formal_teacher_pipeline_controller.log
```

### 3.3 候选收集器已验证

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

这只是 collector 验证，不是正式候选集；正式收集必须等到 240/240 完成后重跑且得到 `PASS_COMPLETE_COLLECTION`。

同一 partial 集的 fast gate 集成验证：

```text
FORMAL_ELIGIBLE = 603 / 709（85.0%）
HARD_FAIL       = 106 / 709

主要失败：
CDR N-linked glyco motif = 101
CDR homopolymer >=5      = 7
```

这一结果说明生成库的大多数序列可进入模型前筛，但不能取消正式全库 fast gate。

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

## 六、接下来按此顺序执行

1. 保持 Node1 RFantibody 生产运行，直到 240/240 task 完成且 0 失败。
2. V3-G2 已完成并回退 `mean-pooled v3_full`；主门已失败，因此 null controls 记为不必要的后续晋级计算，而不将其伪装为 PASS。
3. 对 8,640 raw 输出运行 collector，冻结 exact-dedup candidate manifest。
4. 运行快速 hard gate 和通用 prior；按预注册配额抽取约 500 条 teacher，不机械取模型 Top 500。
5. 生成正式 monomer + HADDOCK + 8X6B/9E6Y + contact-frequency teacher 包。
6. 用 parent-cluster split 训练 V3-P，并做 leave-parent/method challenge。
7. V3-P 只负责进入昂贵 Node1 的前筛排序；最终提交仍由结构、docking、开发性和 portfolio 多样性共同决定。

## 七、当前停止条件

在下列条件全部满足前，不得声称 V3-P 或最终候选准备完成：

```text
RFantibody 240/240 complete
正式 candidate manifest 和 fast-gate audit PASS
约 500 条第一轮 prospective teacher 完整生成
teacher per-pose/contact-frequency 字段完整
V3-G formal gate 有明确 PASS/FAIL
V3-P parent-cluster test 和 target-dependence controls 完成
```

因此，当前的直接答案是：**先生成 PVRIG docking teacher 数据是正确且必要的，但它应与 V3-G 通用数据处理和训练并行推进，而不是让两条路径串行等待。**
