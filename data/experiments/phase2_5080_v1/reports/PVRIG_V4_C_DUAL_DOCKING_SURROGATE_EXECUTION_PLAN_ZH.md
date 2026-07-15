# PVRIG V4-C 双构象计算代理：执行方案与当前状态

更新时间：2026-07-15 17:55 CST

## 1. 当前决定

用户给出的建议可以采用，而且应当分成两条互不混淆的路线。

### 路线 A：正式科学路线

继续冻结 V1.3 的失败结论：

```text
FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN
p2_training_ready=false
```

V1.3 不改阈值、不删 anchor、不从 sensitivity grid 中挑结果，也不把 G1-G5 直接改成训练标签。正式 V3-P2 仍需新的独立 blocker family、实验 binding/blocking 证据和新的 family-level holdout。

### 路线 B：比赛计算前筛路线

另起版本 `V4-C`：

```text
VHH sequence
    -> fixed-PVRIG computational dual-docking geometry surrogate
    -> continuous geometry rank + uncertainty
    -> allocate real structure/docking budget
```

V4-C 的输出不是：

- PVRIG binding probability；
- Kd 或 affinity；
- PVRIG-PVRL2 实验 competition；
- 真实 blocker probability；
- Docking Gold。

V4-C 只学习：哪些序列更可能在当前固定的 8X6B/9E6Y 独立 Docking 协议下产生较稳健的界面遮挡样计算几何。

## 2. 为什么现在仍值得做预测模型

当前比赛候选资产已经达到：

```text
8,640 raw designs
8,248 exact-unique designs
7,087 fast-gate eligible designs
500 Teacher500 candidates
290 complete Full-QC hard-pass candidates with complete AbNatiV
```

现有 `v3_full` 可以覆盖 7,087 条的大库，但它只是通用弱结合先验。现有 V3-P1 虽然能拟合部分 Teacher 排序，却没有通过正式部署门。因此需要一个新的、边界更窄但监督更可靠的 fixed-target 计算代理。

V4-C 的价值是减少昂贵 Docking 数量，而不是替代 Docking 或实验。

## 3. 当前可用数据

### 3.1 新独立双构象数据：最高质量计算监督

服务器根目录：

```text
/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714
```

冻结任务构成：

```text
128 candidates x 2 conformations x 3 seeds = 768 candidate jobs
47 controls   x 2 conformations x 3 seeds = 282 control jobs
total = 1,050 jobs
```

协议关键点：

- 8X6B 和 9E6Y 独立 Docking；
- 每个构象 3 个独立 seed；
- ATOM-only，排除 HETATM；
- 每个成功 job 至少 4 个完整 native/cross 2x2 pose model；
- full/anchor/holdout hotspot 分开；
- 保留 total/CDR3 occlusion、clash、RMSD、model-pair consistency；
- job、protocol、restraint 和 output 有哈希闭合。

2026-07-15 17:55 的实时状态：

```text
SUCCESS               935
RUNNING                  6
PENDING                108
FAILED_MAX_ATTEMPTS      1
```

控制组已经 `282/282 SUCCESS`。唯一失败 candidate job 在同一 candidate-conformation 仍有另外两个成功 seed，因此仍可能满足最少 2-seed 门，但不能把失败 seed 插补为成功。

### 3.2 Teacher500：与 7,087 大库同域的低保真监督

Teacher500 来自当前正式候选生成域，适合用于：

- 低权重预训练或 replay；
- 检查 V4-C 是否迁移回当前 7,087 候选域；
- 训练序列特征和不确定性基础。

它不适合用于：

- V4-C formal test；
- 独立 9E6Y native Docking 真值；
- 实验 blocker 标签。

### 3.3 47 controls 和 V1.3 anchors

47 controls 用于估计：

- seed 方差；
- receptor 内稳定性；
- receptor 间差异；
- positive/perturbation/destructive control 的评价器行为。

它们不增加独立生物学 family 数。多个 seed、多个 pose 也不能当作多个独立 anchor。

### 3.4 Full QC 290

`teacher500_full_qc_complete290_lineage.csv` 只提供 developability/portfolio 证据，不进入 Docking geometry target。

## 4. 必须承认的 domain shift

新 dual128 与当前 7,087 大库之间：

```text
exact sequence overlap = 0
exact CDR3 overlap      = 0
```

dual128 只覆盖 3 个 scaffold：

```text
ekg 48
qrg 45
qkg 35
```

而 7,087 大库来自 40 个 parent framework cluster。因此 dual128 是很好的独立计算监督，但不能单独证明对 40-parent 大库的泛化。

V4-C 必须同时：

1. 在 dual128 untouched near-CDR3-family test 上验证；
2. 在 Teacher500 同域数据上做低保真迁移诊断；
3. 输出 sequence/embedding distance 或 ensemble uncertainty；
4. 对明显 OOD 的 7,087 候选降低 exploitation 比例；
5. 保留 15%-20% exploration/diversity 配额。

## 5. 已冻结的无标签 split

在读取新 1,050-job campaign 的 result-level Docking 标签前，已经冻结：

```text
OPEN_DEVELOPMENT  96
UNTOUCHED_TEST     32
```

不可拆分的 group 单位：

```text
near_cdr3_family_id
```

用于 label-blind 平衡的字段：

- phase（由 arm_id 推导）；
- scaffold_id；
- 旧 V2 panel 的 selection_bucket；
- h3_regime。

未使用任何新 campaign 的：

- hotspot；
- occlusion；
- native/cross class；
- HADDOCK score；
- seed result；
- R 值。

冻结产物：

- `experiments/phase2_5080_v1/data_splits/pvrig_v4_c/dual128_candidates_source.tsv`
- `experiments/phase2_5080_v1/data_splits/pvrig_v4_c/dual128_split_manifest.tsv`
- `experiments/phase2_5080_v1/data_splits/pvrig_v4_c/dual128_split_audit.json`
- `experiments/phase2_5080_v1/audits/phase2_v4_c_preregistration.json`
- `experiments/phase2_5080_v1/audits/phase2_v4_c_test_spec.json`

限制必须写清：这个 test 是 unseen near-CDR3 family，不是 unseen generator，也不是严格 unseen scaffold。

## 6. 连续 Teacher 标签

V4-C 不使用 V1.3 anchor-fitted G1-G5 作为主监督。

### 6.1 Pose 连续分数

对每个完整 pose model，固定：

```text
soft(x,t) = x / (x+t)

S_pose =
  0.15 * clip(full_hotspot / 23, 0, 1)
+ 0.25 * clip(holdout_hotspot / 11, 0, 1)
+ 0.25 * soft(total_occlusion, 500)
+ 0.20 * soft(CDR3_occlusion, 100)
+ 0.15 * soft(CDR3_fraction, 0.15)
```

这里使用固定物理/旧协议尺度，不使用本轮结果拟合阈值。

### 6.2 Job、receptor 和 candidate 聚合

```text
pose weight       = 1/log2(rank+1)，job 内归一化
R_job             = weighted mean(S_pose)
R_receptor        = median(R_job across successful seeds)
R_dual_mean       = mean(R_8X6B, R_9E6Y)
R_dual_min        = min(R_8X6B, R_9E6Y)
R_dual_gap        = abs(R_8X6B - R_9E6Y)
```

主排序 target：

```text
R_dual_min
```

同时保留：

- R_8X6B；
- R_9E6Y；
- R_dual_mean；
- R_dual_gap；
- 两个 receptor 的 seed SD；
- native/cross support agreement；
- model pair consensus；
- supporting seed count；
- full/anchor/holdout hotspot；
- total/CDR3 occlusion；
- clash 和 overlay RMSD。

G1-G5 可以由 seed/pose bootstrap 形成软分布用于解释，但不是唯一主 target。

实现：

- `experiments/phase2_5080_v1/src/prepare_phase2_v4_c_teacher.py`
- `experiments/phase2_5080_v1/src/test_prepare_phase2_v4_c_teacher.py`

该构建器默认拒绝：

- 1050 jobs 未 terminal；
- fresh evaluator 不是 production `PASS`；
- protocol/job manifest hash 不匹配；
- candidate-conformation 少于 2 个成功 seed；
- 成功 job 少于 4 个完整 model pair；
- 未显式 formal unseal 却请求 32 条 test label。

## 7. 模型训练顺序

不能直接上更大的网络。先运行以下 baseline：

1. constant；
2. scaffold-only shortcut；
3. metadata shortcut；
4. CDR3-only sequence ridge；
5. full-sequence handcrafted ridge；
6. frozen `v3_full` generic-prior-only；
7. frozen V2.3 contact-statistics；
8. label-shuffle null。

第一版真实模型：

```text
frozen sequence embedding
    + small multi-output ridge / two-layer MLP
    -> R_8X6B, R_9E6Y, R_dual_min, R_dual_gap, uncertainty
```

只有它在 grouped open validation 和 untouched test 都超过 shortcut/baseline 后，才允许尝试更复杂的 cross-attention adapter。

当前已经实现 dependency-light grouped ridge baseline runner：

- `experiments/phase2_5080_v1/src/train_phase2_v4_c_baselines.py`
- `experiments/phase2_5080_v1/src/test_train_phase2_v4_c_baselines.py`

训练器只接受 96 条 `OPEN_DEVELOPMENT`，任何 test row 混入都会直接失败。

## 8. 正式验收

32 条 untouched test 只解封一次。至少要求：

- ensemble 超过最强 baseline；
- 3 个 seed 中至少 2 个单独超过 baseline；
- near-CDR3-family bootstrap delta 95% CI 下界 > 0；
- paired group permutation p < 0.05；
- label shuffle 不通过；
- scaffold-only 和 CDR3-only 不能匹配完整模型；
- exact sequence 和 near-CDR3 family 跨 split overlap = 0。

主要指标：

- Spearman(R_dual_min)；
- NDCG over R_dual_min；
- 25% Docking budget 下找回真实 top quartile 的 recall。

因为 V4-C 明确是 fixed-target sequence-only 模型，target permutation/antigen ablation 不是其 promotion gate。任何未来声称跨抗原 target-conditioning 的科学模型仍必须通过这些测试。

## 9. 与 7,087 大库衔接

如果 V4-C formal gate 通过：

```text
70%  surrogate exploitation
15%  uncertainty / disagreement
15%  parent + patch + mode + CDR3 diversity exploration
```

最终排序仍保留分轴证据：

```text
generic binding prior
V4-C computational geometry rank
V4-C uncertainty / OOD
Full QC / developability
real docking evidence
portfolio diversity
```

不能把它们压成一个被误称为“阻断概率”的值。

## 10. 已启动的自动执行

### Node23

生产 controller 继续运行，未停止或改写。另启动只读等待 + terminal 后聚合 watcher：

```text
PID 96641
scripts/monitor_phase2_v4_c_dual128_remote.sh
```

它只在 PENDING/RUNNING 都为 0 后执行 fresh aggregate，并冻结：

- job_results.tsv；
- pose_scores.tsv；
- PROTOCOL_VALIDATION.json；
- EVALUATOR_STABLE.json；
- enrichment report；
- SHA256 清单。

只有 evaluator production PASS 时，Teacher release 才可能 ready。

### Node1

现有 Full QC/Node1 parity 任务保持运行。另使用空闲 GPU 0 准备 dual128 的冻结 `v3_full` generic weak prior，作为 V4-C 必须击败的独立 baseline。该任务不改变 dual128 split，也不读取新 Docking 标签。

## 11. 接下来的触发顺序

```text
Node23 1050 jobs terminal
        -> fresh aggregate
        -> evaluator stability gate
        -> hash freeze
        -> release 96 open continuous teacher rows
        -> grouped simple baselines
        -> frozen embedding + small multi-output model
        -> freeze model/seeds/thresholds
        -> one-shot unseal 32 test rows
        -> PASS: score 7,087 with OOD/uncertainty quota
        -> FAIL: retain v3_full weak prior + QC + diversity + real docking
```

并行科学路线：

```text
分析 V1.3 不稳定 anchors 的连续通道和 bootstrap 分布
        -> 新增至少 3 个独立 blocker family
        -> family 38 补第二 anchor
        -> 新 V1.4/V2.0 方法预注册
        -> 满足 family/holdout 条件后才重新启动正式 V3-P2
```

## 12. 当前停止条件

本轮不会：

- 修补 V1.3 为 PASS；
- 把本轮 partial/stale reports 用于训练；
- 在 evaluator PASS 前发布 Teacher；
- 提前读取 32 条 untouched label；
- 用 47 controls 冒充 47 个独立生物学样本；
- 让新模型阻塞当前比赛 Full QC、真实 Docking 和 Top50 portfolio 工作。

结论：用户给出的建议是正确的。正式 V3-P2 继续冻结；比赛模型以独立版本 V4-C 前进，使用连续双构象计算监督、严格不确定性边界和一次性 untouched test。这样既能利用正在生成的 1,050-job 数据，也不会把尚未成为 Gold 的 Docking 证据包装成生物学真值。
