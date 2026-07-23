# V2.20 Contact-Shared Top5 Challenger：执行计划 DRAFT_V2

## 0. 文档状态

```text
DRAFT_V2_ONLY
NOT_FROZEN
NO_MATERIALIZATION_AUTHORIZED
NO_TRAINING_AUTHORIZED
NO_DEVELOPMENT_OR_TEST_ACCESS_AUTHORIZED
```

本稿响应第一次 critic review 的 P0/P1 问题。它只定义下一轮实现、审计和正式冻结所需的完整合同，不授权读取 development 坐标、不授权生成正式 teacher，也不授权训练。

原稿保留且不覆盖：

```text
PLAN_ZH.md                    SHA256 190ac5156ef3390816852fd75737f016eb6fa8bb44feec1ef41bbab02e7ca280
PREREGISTRATION_DRAFT.json    SHA256 acec1d81121059d823f3b71d85627e311cdaa19d31810f1d6a7882a2b09d6b88
```

二者现在仅具有：

```text
SUPERSEDED_BY_DRAFT_V2_FOR_REVIEW_ONLY
```

正式实施前还必须由独立 critic 审查 DRAFT_V2、实现 14 项最小测试、写出新的 implementation freeze。不得把本稿改名为 freeze。

---

## 1. 目标和证据边界

V2.20 要回答一个窄问题：

> 在完全相同的 9,849 条 scalar train、whole-parent 五折、seed43 和 Top5 evaluator 上，给共享 encoder 增加来自独立 8X6B/9E6Y Docking Top-K pose 的 residue-contact 辅助监督，能否提高 `R_dual_min` 的 Top 5% 早期富集？

生产输入仍然只有：

```text
VHH sequence
+ frozen ESM2-650M residue states
+ label-free VHH monomer graph
+ fixed public 8X6B target graph
+ fixed public 9E6Y target graph
```

预测目标仍然只是：

```text
independent dual-receptor computational Docking geometry surrogate
```

它不是：

```text
binding / Kd / experimental PVRIG competition / functional blocking
expression / purity / Docking Gold / final submission truth
```

---

## 2. DRAFT_V2 对 critic P0/P1 的逐项修复

| critic 项 | DRAFT_V2 固定处理 |
|---|---|
| split allowlist 必须早于任何 stat/hash/open | 先加载唯一 split manifest，构建 train allowlist；候选级 `stat/lstat/exists/glob/hash/open/gzip/parse` 均只能发生在过滤之后，并用 instrumented opener 测试 |
| V29 train-only materializer 与 development 隔离 | production materializer 只产生 738 条 train teacher；development 使用另一 invocation、另一物理 root，且只能在模型预测和 gate 冻结后运行 |
| C0 weight=0 配对对照 | C0/C1 使用同一 V2.20 代码、模型、参数顺序、optimizer group、batch order 和序列化初始化；C0 仅把 contact weights 设为 0 |
| 初始化 hash | 每 fold/seed 冻结 full-head state、scalar/shared substate、parameter order、optimizer group 和 epoch batch-order hashes；C0/C1 启动前必须完全相等 |
| 精确复刻 V2.13 scalar 合同 | 明确列出 Huber、softmin、top-weight percentile、batch normalization、shuffle、accumulation remainder、clip、AdamW、fixed 8 epochs |
| 绑定五折和 B0 OOF | 绑定五份 split/contract/pred/checkpoint/history/result 哈希；先从原五折逐行重建 B0 aggregate，并要求序列化数值逐字段完全相等 |
| contact weight | 每 outer fold 只用 fit parents 的 8 个固定校准 batch 做 prediction-blind gradient-ratio calibration；网格、选择规则和 fail rule 预先固定 |
| source/V4D/availability/position diagnostics | 正式报告 V4D/V4H/V29 分层 contact 指标、contact available/unavailable scalar 指标、availability-only diagnostic、position-only baseline 和 V4D-only ablation |
| seed917 命名 | 统一改为 `seed917_included_multiseed`；1931+3253 两 seed但无917的7条 V29 train 不进入 primary |
| PCGrad/gradient conflict | V2.20 Phase-1 固定 `PCGrad=false`；普通 loss sum；校准期严重负冲突触发 fold prelaunch fail，训练中只记录不动态干预 |
| contact batch/reduction/negative universe | 完整定义 dense universe、有效零、技术 NA、无 negative sampling、balanced soft BCE、单类/双类/receptor/candidate reduction |
| promotion/bootstrap/ablation | 给出数值门槛、10,000 次 whole-parent paired bootstrap、source-stratified 规则和四项目标/标签 ablation 门槛 |
| 14 项测试 | 第 15 节列出 14 项可自动判定的最小测试 |

---

## 3. 冻结 scalar 数据和 B0 基线

### 3.1 Scalar teacher

```text
primary_D1_canonical10644_teacher.tsv
SHA256 46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3

primary_D1_canonical10644_split_manifest.json
SHA256 9dc416dcf8694f321a5432ba8574f0229c03527af14926fcf2f43ee4211f07ed
```

规模：

```text
train             9,849 rows / 54 parents
open development    795 rows / 10 parents
```

直接预测：

```text
R_8X6B
R_9E6Y
```

评价与推理：

```text
R_dual_min = exact min(pred_R8, pred_R9)
```

禁止独立第三输出 `pred_Rdual`。

### 3.2 B0 冻结外部基线

B0 是未修改的 V2.13 L1 seed43 strict whole-parent OOF：

| 指标 | B0 |
|---|---:|
| EF_true_top10@budget5 | 3.0828512886 |
| hits / selected | 152 / 493 |
| precision@5 | 0.3083164300 |
| recall@5 | 0.1543147208 |
| Rdual Spearman | 0.5661935645 |
| Rdual MAE | 0.0362309829 |

冻结 aggregate：

```text
TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv
SHA256 d441a47e938a0c490cead10c80e6b71bd1a22abe9e22803ed1af43ec04f60669

OOF_METRICS.json
SHA256 49b2f0c3fde3a1395ea09e8337e04aade35a3daaf2b2ed81b0118d58df42c73e

OOF_RECEIPT.json
SHA256 221c2b1b70710c7612777428026d8cfc943a94eab36881cf3755666d023458c0
```

在任何 C0/C1 训练前，必须从绑定的五份原始 fold prediction 重建 aggregate，并逐行比较：

```text
candidate_id
sequence_sha256
parent_id
fold_id
seed
true_R8 / true_R9 / true_Rdual
pred_R8 / pred_R9 / pred_Rdual
```

数值按原 TSV 序列化字符串完全相等，不使用 tolerance。

### 3.3 B0 与 C0 不是一回事

```text
B0 = 原 V2.13 外部冻结基线的证据重放
C0 = 新 V2.20 同代码、同初始化、contact weight=0 的配对对照
C1 = 新 V2.20 contact weight>0 challenger
```

新 contact modules 会改变模型构造和随机数消费，因此不应伪称 C0 必然与旧 B0 checkpoint 位级一致。正确做法是：

1. B0 单独通过原五折逐行重放验证；
2. C0/C1 在新架构内严格配对；
3. C1 promotion 必须同时击败 B0 和 C0。

---

## 4. 五折不可变绑定

| fold | train/score rows | train/score parents | split SHA256 | contract SHA256 |
|---:|---:|---:|---|---|
| 0 | 7870 / 1979 | 44 / 10 | `33f99c...6617` | `3b4a8c...265b` |
| 1 | 7869 / 1980 | 44 / 10 | `cdfa29...0d1e` | `eef20c...6ad` |
| 2 | 7880 / 1969 | 44 / 10 | `915eca...08d` | `ffd254...12db` |
| 3 | 7848 / 2001 | 44 / 10 | `850818...b4b` | `006e34...e1a` |
| 4 | 7929 / 1920 | 40 / 14 | `4ea0bb...17d` | `ca221a...e96` |

完整 SHA256 均写在 `PREREGISTRATION_DRAFT_V2.json`。其中 fold2 额外绑定：

```text
train parent set ef4afd9a71bd532daada6482961721ded002bf1bc1fd281f9f42cdf60403767b
score parent set a33793e5be351ba0099b89452fb4012198bf0accc9ce79a37f19fac2377c447f
```

其余 parent-set hashes 也在 JSON 中绑定。任何 fold 重排、parent 移动、score row 用于 contact calibration 都是 fail-closed。

---

## 5. Split-before-access 防泄漏合同

这是 DRAFT_V2 最重要的材料化改变。

### 5.1 唯一允许的操作顺序

```text
1. 只读取并验证 frozen scalar split manifest
2. 在内存中构建 train-only：candidate_id + sequence_sha256 + parent_id allowlist
3. 只用非坐标 source metadata 与 allowlist 连接
4. 在路径解析前拒绝 development / frozen / quarantine / unknown
5. 只对剩余 train allowlist 解析坐标路径
6. stat regular+nonempty
7. sha256
8. open / decompress / parse coordinates
9. 输出 immutable train-only contact teacher 和 receipt
```

在第 4 步以前，下列候选级操作全部禁止：

```text
stat / lstat / exists / glob / path expansion
sha256 / open / gzip.open / PDB parse / numeric target parse
```

实现测试必须替换所有文件访问入口为 recording wrapper，并证明非 train 候选访问计数为 0。仅在日志里声称“没有打开”不够。

### 5.2 Development 的物理隔离

production materializer 必须满足：

```text
output rows                         738 train only
development rows in output          0
development paths resolved          0
development files stat/hash/open    0
frozen/quarantine stat/hash/open    0
```

120 条可用 development contact 数据不得和 train package 同进程或同输出 root。未来只有在：

```text
C0/C1 predictions frozen
+ model hashes frozen
+ promotion gates frozen
+ critic approves one-shot development evaluation
```

之后，才能由另一个显式 development materializer 在另一个物理目录生成。

---

## 6. Primary contact teacher

### 6.1 来源和数量

```text
V4-D 3-seed                         113
V4-H 3-seed                         107
V4-H 2-seed                         213
V29 seed917_included_multiseed      305
---------------------------------------
primary train                       738 / 53 parents
```

唯一没有 primary contact teacher 的 scalar train parent：

```text
C0052
```

排除：

```text
V4-H single-seed                  849
V29 1931+3253 but no seed917        7
all development                   120
all frozen/quarantine               0
```

术语必须使用：

```text
seed917_included_multiseed
```

不得再写可能误导为所有 seed 与 scalar 完全一致的 `seed917_aligned`。

### 6.2 V29 新 train-only materializer

V29 release 中 `pose_pdb_sha256` 全为空，所以不能直接信任 path table。只允许使用 Node1 lab coordinates，并为每个 Top-K PDB 新建 content-addressed manifest。

每个文件必须：

```text
regular file
non-empty
gzip 可解压
ATOM-only 解析成功
candidate/receptor/seed/rank/model provenance 闭合
SHA256 写入 immutable manifest
```

stage2/external/stage3 未镜像坐标一律不进入本版本。不得用 score table 代替 coordinates 生成 contact。

### 6.3 Teacher 定义

每个有效 job：

```text
receptor: 8X6B or 9E6Y
Top-K: fixed 8
contact cutoff: 4.5 Å
pose weight: normalize(1/log2(rank+1))
seed weight: paired successful receptor seeds equal weight
pair variance: population variance over seed-level pair means
uncertainty: 1/(1+4*variance)
```

目标图固定 node order：

```text
8X6B: 103 nodes
9E6Y: 108 nodes
```

VHH residue order必须绑定 model residue mask、candidate sequence SHA 和 residue-index mapping。

---

## 7. Dense contact universe 与技术 NA

Sparse TSV 中没有出现的 pair，只有在下列闭包全部通过后才能变成零：

```text
candidate valid
receptor valid
VHH residue mapping valid
fixed target node mapping valid
all required Top8 coordinates valid
paired seed set valid
```

随后定义：

```text
pair universe     = every valid VHH residue × every fixed receptor node
marginal universe = every valid VHH residue for each receptor
```

对 valid universe：

- sparse 表中出现的 pair 使用 soft mean；
- 未出现的 pair 才是 `target=0, mask=1, uncertainty=1`；
- 技术缺失、receptor 缺失、mapping 失败是 `mask=0`，不是 negative；
- 不能使用数字 sentinel 或把 NA 写成 0。

---

## 8. 模型架构：正交 terminal heads

### 8.1 共享部分

```text
frozen ESM2-650M residue states
+ VHH label-free graph encoder
+ 8X6B/9E6Y fixed target graph encoders
→ shared low-rank pair representation
```

### 8.2 分离 attention 和 contact 的最后 logits

```text
shared pair representation
  ├── attention projection
  │     + independent conformer-specific positive temperature
  │     → bidirectional attention pools
  │     → direct R8 / R9 scalar heads
  └── contact projection
        + receptor-specific calibration bias
        → pair contact logits
        → marginal contact logits
```

两支可共享 encoder 梯度，但最后标量 logits 不共享。这样：

- attention 可以学习相对尖锐的路由；
- contact 可以学习绝对概率校准；
- contact BCE 不再直接强迫 attention logits 饱和；
- contact 预测不作为 scalar head 的显式输入，避免 pose teacher shortcut。

### 8.3 双受体一致性

模型只直接输出：

```text
pred_R8
pred_R9
```

训练辅助量：

```text
softminτ = -τ logsumexp([-R8/τ,-R9/τ]) + τ log(2)
τ = 0.02
```

真值为 exact min。评价和推理始终：

```text
pred_Rdual = min(pred_R8,pred_R9)
```

禁止独立第三头，以保证 `Rdual <= R8,R9`。

### 8.4 Forward firewall

禁止作为 neural forward 输入：

```text
candidate/parent/campaign/source IDs
contact availability / seed count / reliability tier
Docking pose / pose-derived features / true contact labels
M2 / C2 outputs
```

source、availability、tier 只可用于 loss mask、审计和分层报告。

---

## 9. 三模型对照

### B0：冻结外部基线

原 V2.13 五折 OOF，只重放，不重新训练。

### C0：同代码 weight=0

```text
V2.20 full architecture
contact modules instantiated
marginal_weight = 0
pair_weight = 0
```

contact modules仍在 state dict 和 optimizer group 中，但无 contact gradient。

### C1：contact-shared challenger

与 C0 唯一的因果差别：

```text
marginal_weight > 0
pair_weight = 0.5 * marginal_weight
```

每 fold/seed：

- C0/C1 从同一个序列化 full-state 初始化；
- full state hash相同；
- scalar/shared substate hash相同；
- parameter name order 和 optimizer groups相同；
- epoch batch-order hashes相同；
- 两者在独立确定性进程运行；
- 启动顺序按 fold parity 交替，避免固定 launch-order 偏差。

C1 必须击败 B0 和 C0，不能只和其中一个比较。

---

## 10. 精确 V2.13 scalar loss 与训练合同

```text
epochs                 8
batch size             8
eval batch size       16
grad accumulation      4
precision              BF16
optimizer              AdamW
learning rate          1e-4
weight decay           0.02
grad clip norm         1.0
graph hidden dim       128
dropout                 0.25
Huber beta              0.03
receptor weight         1.0
dual weight             0.5
softmin tau             0.02
top strength            3.0
top center              0.85
top scale               0.05
pair rank weight        0
balanced top/batch      0
seed                    43
```

### 10.1 Top hierarchy weight

只在 outer-fit truth 上计算 exact-min percentile：

```text
rank = scipy.rankdata(exact_min_truth, method="average")
percentile = (rank-1)/(n-1)
top factor = 1 + 3/(1+exp(-(percentile-0.85)/0.05))
row weight = manifest_sample_weight * top factor
```

每个 minibatch 中再除以 batch weight sum。

### 10.2 Scalar loss

每候选 receptor loss：

```text
mean over R8/R9 SmoothL1(pred,true,beta=0.03,reduction=none)
```

每候选 dual loss：

```text
SmoothL1(softmin(pred_R8,pred_R9), exact_min(true_R8,true_R9), beta=0.03)
```

总 scalar：

```text
1.0 * normalized_weighted_mean(receptor loss)
+ 0.5 * normalized_weighted_mean(dual loss)
```

### 10.3 Batch/optimizer

```text
random.Random(seed+epoch).shuffle(all outer-fit indices)
→ sequential chunks of 8
→ ordinary final short batch
→ no replacement / no contact balancing
```

每 batch loss 先除以 4 再 backward。末尾若 remainder=`r<4`，step 前把累计梯度乘 `4/r`，再 clip norm 1.0，再 AdamW step。固定 8 epochs、无 early stopping、无 dev selection，frozen backbone 始终 eval。

---

## 11. Contact batch、reduction 和 loss

Contact supervision 被动附着于第 10 节完全相同的 scalar batch；不得为了 contact 可用性改变 batch 成员或顺序。

### 11.1 Dense target

- valid candidate/receptor：构建完整 dense universe；
- sparse soft positives填入；闭包后 absent pair填0；
- unavailable candidate/receptor：全 mask=0；
- 不做 1:3 或其他 negative subsampling。

这与现有经过 smoke 的 `balanced_soft_bce_per_candidate` 实现一致，也避免 C0/C1 因采样器不同失去配对。

### 11.2 每候选 balanced soft BCE

把 logits、soft target、uncertainty、mask flatten：

```text
w_pos = uncertainty * mask * target
w_neg = uncertainty * mask * (1-target)
```

分别计算：

```text
positive mean = sum(w_pos * softplus(-logit)) / sum(w_pos)
negative mean = sum(w_neg * softplus(logit))  / sum(w_neg)
```

- 两类都有：`0.5*positive_mean + 0.5*negative_mean`；
- 只有一类：使用该类 mean；
- 两类都无：candidate/receptor unavailable。

先平均每候选可用 receptors，再用：

```text
batch-normalized scalar hierarchy weight
× seed tier weight
× eligibility mask
```

做 eligible-candidate weighted mean。整 batch 无 contact 时返回 differentiable zero。

### 11.3 Tier 和总 loss

```text
3-seed weight = 1.0
2-seed weight = 0.8
1-seed weight = 0.0
pair weight   = 0.5 * marginal weight
```

C1：

```text
L = L_scalar + λm*L_marginal + 0.5λm*L_pair
```

C0：

```text
L = L_scalar + 0*L_marginal + 0*L_pair
```

---

## 12. Per-fold contact weight calibration

不再留下“训练前再决定”的自由度。

每 outer fold/seed，在 optimizer 创建前：

1. 加载 C0/C1 共同初始 state；
2. 只使用 outer-fit parents；
3. 按 frozen seed43 epoch0 order 取最先出现的 8 个 contact-eligible scalar minibatches；
4. 不做 optimizer step；
5. 对共享参数分别计算 scalar gradient norm 和未加权 contact gradient norm；
6. 测试固定 grid：

```text
λm ∈ [0.00015625, 0.0003125, 0.000625, 0.00125, 0.0025]
λp = 0.5 λm
```

定义：

```text
ratio = λm * ||g_contact_shared|| / ||g_scalar_shared||
```

选择：

- 取 median ratio 落入 `[0.05,0.15]` 的最小 λm；
- 若没有，取 median ratio 最接近 0.10 的 λm；
- 并列取更小 λm。

整个 calibration 禁止生成 prediction、EF、score-parent loss 或 dev metric。选择结果在 optimizer 创建前写入 receipt。C0 记录同一个已选 λm，但实际乘0。

---

## 13. Gradient conflict：本版不使用 PCGrad

Phase-1 固定：

```text
PCGrad = false
ordinary summed gradients
```

校准期 fail rule：

```text
若8个 batch 中超过2个的 scalar/contact shared-gradient cosine < -0.50
→ fold PRELAUNCH_FAIL
→ 不创建 optimizer，不训练，不调权重补救
```

训练期间记录每 step/epoch：

```text
gradient cosine
gradient norm ratio
contact-eligible row count
```

但日志只能诊断，不能动态投影梯度、改 λ、跳过 batch、延长 epoch 或重启挑 seed。若本版因冲突失败，PCGrad 只能另起 V2.21 预注册。

---

## 14. 诊断和 ablation

### 14.1 Source-stratified

在 outer-score 中有真实 contact teacher 的 rows 上分别报告：

```text
V4-D
V4-H
V29
```

每层报告 marginal/pair AUPRC、Brier、样本数、parents。禁止只报 pooled contact 指标。

### 14.2 Availability 分层与 baseline

Scalar OOF 分层：

```text
contact_teacher_available
contact_teacher_unavailable
```

另建 diagnostic-only availability score：

```text
score=1 if primary train materializer has contact teacher else 0
candidate_id tie-break
```

它只能量化 acquisition bias，不能进入 neural forward 或 production ranking。

### 14.3 Position-only baseline

在每个 outer-fit 内估计：

```text
P(contact | receptor, IMGT region, VHH residue position)
```

不读取 sequence、graph、target residue identity、source、parent、candidate。C1 contact AUPRC 必须超过它，证明不是只学 CDR/位置先验。

### 14.4 V4D-only ablation

同 C1 scalar rows、fold、初始化和代码，但 contact loss 只使用 outer-fit V4-D 113 条。它是 source robustness 诊断，不参与 production promotion，也不能替代 full C1。

### 14.5 四项强制 ablation

1. `target_residue_embedding_permutation`：固定 seed20260723，target node内置换；
2. `hotspot_mask_shuffle`：保持正例数量，target node内置换；
3. `8X6B_9E6Y_conformer_swap`：交换 receptor graph 通道但不交换 label 名称；
4. `contact_label_shuffle`：只在 outer-fit `source×parent×receptor` 内，seed20260723，完整五折重训。

任何 outer-score contact label 都不能用于 shuffle 构造或训练。

---

## 15. 正式冻结前 14 项最小测试

1. **Pre-access test**：instrumented wrapper 证明 allowlist filter 早于所有候选级 stat/hash/open/glob/parse。
2. **Train-only isolation**：development/frozen/quarantine/unknown 的 path resolution 和访问计数均为0。
3. **V29 coordinate closure**：lab Top-K 坐标 regular、nonempty、可解压、逐文件 hash、manifest闭合。
4. **Seed rule**：`seed917_included_multiseed` 必须 >=2 paired receptor seeds 且含917；1931+3253-only 被拒绝。
5. **Top8/NA rule**：receptor、seed、Top8闭合；technical NA 不变成零-contact negative。
6. **Join/count rule**：candidate/sequence SHA/parent/split一对一，精确复现738 rows/53 parents。
7. **Dense universe golden test**：103/108 target nodes、VHH order、valid absent-zero、invalid mask-zero均正确。
8. **Contact reduction golden test**：双类、positive-only、negative-only、缺receptor、缺candidate、tier weight、differentiable zero。
9. **Scalar parity**：V2.13 Huber/softmin/top percentile/batch normalization对 frozen golden tensors完全一致。
10. **Batch/optimizer parity**：shuffle、chunk、remainder rescale、clip、AdamW groups及C0/C1 data order一致。
11. **Five-fold/B0 replay**：五折全部哈希绑定；aggregate逐行/逐字段/序列化数值完全重建。
12. **Initialization pairing**：C0/C1 full state、scalar/shared substate、parameter order、optimizer groups、epoch batch hashes一致。
13. **Firewall/autograd/conflict**：拒绝所有禁用输入；验证 frozen backbone、shared/contact gradient roles、PCGrad-off和prelaunch fail rule。
14. **Evaluation fixture**：bootstrap、promotion、source/availability/position/V4D-only和四项ablation在合成PASS/FAIL案例上确定性判定。

必须在一次 immutable test log 中全部 PASS。不得分多次挑选成功日志拼接。

---

## 16. 评价、bootstrap 和量化 promotion

主指标：

```text
EF_true_top10_at_budget5
```

`EF5=5.0` 是 aspirational engineering target，不是为了让本轮“容易通过”而降低的 minimum。

### 16.1 Whole-parent paired bootstrap

```text
replicates: 10,000
seed: 20260723
unit: whole parent cluster
```

每次从54个 parent有放回抽54次，重复抽到的 parent保留其全部 rows，并给重复 candidate附 draw ordinal 仅用于稳定 tie-break。每次重新按 frozen evaluator 计算 replicate 内 true top10 和 budget5。

报告 paired percentile 95% CI：

```text
C1 - C0
C1 - B0
```

### 16.2 所有 promotion 条件必须同时满足

早期富集：

```text
C1 pooled EF5 >= max(B0,C0) + 0.10
C1 hits@5     >= max(B0,C0) + 5
bootstrap 95% CI lower(C1-C0) > 0
bootstrap 95% CI lower(C1-B0) > 0
```

fold stability：

```text
至少4/5 folds: C1-C0 EF5 >= -0.25
任一 fold:      C1-C0 EF5 >= -0.75
```

回归 guardrails：

```text
EF10      >= 2.5652
Spearman  >= 0.5362
MAE       <= 0.03985
```

contact/source/ablation：

```text
intact pair AUPRC >= position baseline * 1.10
至少2/3 source strata超过position baseline
residue permutation: pooled contact AUPRC相对下降 >=10%
hotspot shuffle:      pooled contact AUPRC相对下降 >=10%
conformer swap:       receptor MAE增加 >=0.001
label shuffle:        EF5 gain over C0 <=0.10
label shuffle:        AUPRC gain over position baseline <=5% relative
```

若某 source score rows不足以计算指标，不能静默跳过；该 source gate记为 `INSUFFICIENT_PREDECLARED_SUPPORT`，整体不 promotion，除非在正式 freeze 前由新版本重新定义门槛。

禁止：

```text
看结果后改阈值
删除坏 fold/seed/source
重标 technical NA
重新选择 contact λ
更换 bootstrap seed/replicates
只报告 pooled、不报告分层
```

---

## 17. 实施顺序

本 DRAFT_V2 经 critic 接受后，仍需按顺序执行：

### Phase I：只实现和测试，不读取坐标

1. split-first instrumented filesystem firewall；
2. train-only materializer dry-run（synthetic fixtures）；
3. dense contact builder/reduction golden tests；
4. B0 five-fold replay verifier；
5. C0/C1 initialization pair materializer；
6. calibration/conflict/evaluator/ablation tests。

### Phase II：正式 implementation freeze

冻结：

```text
code SHA256
14-test immutable log SHA256
fold manifests and B0 replay receipt
V29 source metadata hashes
coordinate allowlist hash
model architecture/config
calibration grid/rule
promotion/bootstrap/ablation config
runtime environment/GPU/container
```

### Phase III：train-only teacher materialization

只生成：

```text
738 candidates / 53 parents
```

逐项验证 receipt 和零泄漏计数。任何计数、hash、closure 不符即 fail-closed；不得临时降到734或补入single-seed。

### Phase IV：B0 replay → C0/C1 seed43 strict OOF

1. B0逐行重放通过；
2. 每fold初始化hash配对；
3. prediction-blind λ calibration；
4. conflict prelaunch gate；
5. C0/C1 五折；
6. locked evaluator、bootstrap、diagnostics、ablations；
7. 一次性 promotion verdict。

### Phase V：只有 Phase-IV promotion 后

```text
seeds 43 / 917 / 1931
ensemble = mean_R8 and mean_R9 then exact min
```

坏 seed 不得删除。

### Phase VI：open development one-shot

只有模型、ensemble、prediction files 和 gates 都冻结后才可使用独立 development materializer。frozen test 继续 sealed。

---

## 18. 为什么这版比 DRAFT_V1 更可审计

DRAFT_V1 的方向正确，但还留下了会影响结果解释的自由度：

- 可能在 allowlist 前触碰 development 路径；
- B0 与新 C0 的角色不清；
- scalar 复刻停留在名称而不是数值合同；
- contact negative universe、batch 和 reduction 未完整闭合；
- λ、gradient conflict 和 PCGrad 留有选择空间；
- pooled 指标可能掩盖 source/availability/position shortcut；
- promotion 和 ablation 缺少可机判数值。

DRAFT_V2 将这些自由度前移到训练前、写成可测试合同。它仍不保证 contact supervision 会提升 Top5；它保证的是：若提升，证据能更可信地归因于 contact auxiliary，而不是 split 泄漏、采样、初始化、availability 或事后调参。

---

## 19. 当前结论

当前可行的 primary 方案是：

```text
9,849 scalar train rows
+ 738 train-only multi-seed contact rows / 53 parents
+ orthogonal attention/contact terminal heads
+ exact V2.13 scalar training contract
+ same-code C0/C1 paired OOF
+ B0 external replay
+ whole-parent bootstrap and target/source ablations
```

但现在仍是：

```text
PLAN COMPLETE FOR REVIEW
IMPLEMENTATION NOT FROZEN
TRAINING NOT AUTHORIZED
```
