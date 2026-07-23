# V2.21 EF5 Targeted Multistage：严格分阶段推进计划

## 0. 文档状态与不可越过的前置门

```text
DRAFT_ONLY
NO_IMPLEMENTATION_FROZEN
NO_TRAINING_AUTHORIZED
NO_OPEN_OR_FROZEN_PROSPECTIVE_ACCESS_AUTHORIZED
```

本目录只固化下一轮设计，不实现、不训练，也不修改 V2.20/V1.2、未来 V1.3 或任何既有冻结数据。

任何 V2.21 计算必须等待新的 V1.3 技术恢复版本完成，并发布一个 **valid scientific terminal**：五个 C0/C1 pair、OOF collection、evaluator 和 frozen core gate 必须全部技术闭合，terminal 可以是科学 PASS 或科学 FAIL。仅完成训练、仅修复 calibration receipt、仅获得五折输出，或任何 technical FAIL，都不构成启动授权。

V1.3 科学 PASS 后走 P1→P2→P3→P4 主线。V1.3 在技术闭合后科学 FAIL，则只能按预注册的 F1–F5 根因分支进入对应 V2.21 新方法；不得追溯改动 V2.20/V1.3 或声称它们 PASS。纠正 contact-loss 权重范围属于 V2.21-A，不能伪装成 V1.3 技术恢复。

证据边界始终是：

```text
独立 8X6B/9E6Y 双受体计算 Docking 几何 surrogate
```

不是 binding、Kd、实验竞争/阻断、表达、纯度、Docking Gold 或最终提交真值。

---

## 1. 目标、现状与为什么需要分阶段

冻结训练评价集合：

```text
9,849 candidates
54 whole-parent clusters
5 fixed outer folds
truth positive = global R_dual_min Top 10%
budget = predicted Top 5%
selected = 493
positives = 985
```

终极工程目标：

```text
EF_true_top10_at_budget5 >= 5.0
hits_at_budget5 >= 247 / 493
precision_at_budget5 >= 0.50
recall_at_budget5 >= 0.25
```

当前 causally valid L1 参考为：

```text
EF5  = 3.0828512885987585
hits = 152 / 493
```

距离目标仍约差 95 hits。既有证据显示：

- 四模型 Top5 union 覆盖 325 个真阳性，oracle EF5 约 6.59；
- 扩展 union 覆盖 346 个真阳性，oracle EF5 约 7.02；
- ListMLE、SoftTopK、普通 hard-negative 分类、raw HGB/ExtraTrees 和 pose-aux cross-fit 都没有超过 L1；
- 因此主要瓶颈是困难候选中的二次辨别和跨 parent 稳健性，而不是继续无约束增加分类头。

描述性 fixed-HGB 的 EF5 约 3.31 不能用于晋级：其 meta outer-train 特征来自全局 base OOF，而这些 base 模型可能训练过当前 meta outer-test parents。V2.21 必须执行真正的双层 cross-fitting，不能复用这一捷径。

---

## 2. V1.2 技术失败与 V1.3 前置恢复边界

已在不读取 OOF 预测的前提下确认：V1.2 folds 0–3 的 C0/C1 `CONTACT_WEIGHT_CALIBRATION.json` 哈希均不同，而冻结 pair validator 要求 exact hash equality。即使所选权重均为 `0.0025`，V1.2 仍必须 fail closed。

V1.3 最小技术恢复应当：

1. 每个 fold 从共享冻结初始 state 只做一次 deterministic FP32 calibration；
2. 输出单一 immutable calibration receipt 和 SHA256；
3. C0/C1 只读取相同路径和相同哈希，禁止各自重算；
4. fresh root 重跑 5 folds × 2 arms；
5. 重新执行 causal pairing、OOF collection 和 frozen core gate。

V1.3 不得修改原 V2.20 lambda grid 或科学门槛。当前 calibration receipt 还显示：最大 `lambda=0.0025` 时 achieved shared-gradient ratio 仅约 `0.000505–0.000538`，远低于原目标 `0.05–0.15`。这是未来新方法的重要诊断，但不能在 V1.3 内修正。

V2.21 的启动前提是未来冻结的 valid scientific terminal：

```text
V1.3 pair/OOF/evaluator/core-gate technical closure = PASS
AND
V1.3 scientific terminal = PASS or FAIL
```

其路径、schema、SHA256、scientific status 和根因分类所需字段必须在 V2.21 implementation freeze 前补齐。无 terminal、technical FAIL、pair/OOF 不闭合、evaluator 失败或 terminal 哈希不符时必须保持未启动。

---

## 3. 固定分支与执行顺序

```text
V1.3 valid scientific terminal
        ├── scientific PASS
        │       ↓
        │   P1 contact causal ablations
        │       ↓
        │   P2 multi-seed uncertainty / reliability
        │       ↓
        │   P3 strict nested compact L1+B+M2+C2 stack
        │       ↓
        │   P4 parent-balanced LambdaLoss Top-K rank head
        │
        └── scientific FAIL
                ├── F1 UNDERPOWERED_CONTACT_LOSS → V2.21-A corrected contact-ratio method
                ├── F2 contact learnable but scalar path ineffective → V2.21-B stop-gradient contact-summary late fusion
                ├── F3 contact not learnable/target-blind → STOP and acquire new multi-seed contact teacher
                ├── F4 fold/source/reliability instability → V2.21-C reliability-weighted method
                └── F5 scalar correlation improves but EF5 does not → V2.21-D separate Top-K rank head
```

根因分支按 `F1→F2→F3→F4→F5` 优先级评估，命中第一个完整定义后停止，不允许同一 terminal 事后挑选多个有利解释。PASS 主线不得交换顺序；不得看到后续结果后回改前一阶段门槛；不得跳过 P1 直接把 contact 模型送入融合。

### 3.1 FAIL 根因分类与对应方法

#### F1 — `UNDERPOWERED_CONTACT_LOSS`

要求 valid scientific FAIL，且 calibration 所有 folds 都使用 fallback/grid maximum，achieved median shared-gradient ratio 均低于冻结目标下界的 10%。当前 V1.2 诊断约为 `0.0005` vs `0.05`，但正式分类只能读取技术闭合后的 V1.3 receipts。

V2.21-A 必须新预注册：以 outer-fit-only 共享 calibration receipt 选择能达到 shared-gradient ratio `0.05` 的 contact weight，C0=0、C1=冻结新权重，fresh 10 arms。新 grid、冲突门、上限和稳定性测试必须在实现前冻结。

#### F2 — Contact 可学，但 scalar 路径无效

要求 heldout-parent contact evaluator 显著超过 position-only baseline，但 C1 对 C0 的 EF5/hits 无显著增益。V2.21-B 使用预测 contact summaries（hotspot/off-interface mass、specificity、CDR1/2/3 mass、entropy、conformer gap），先 stop-gradient，再输入小型 residual/rank head；真 contact 标签不得进入 scalar inference。

#### F3 — Contact 不可学或 target-blind

若 heldout contact 不超过 position-only，或 target permutation/contact-label shuffle 不使指标显著下降，停止 contact 模型调参；只能增加 independent multi-seed Docking/contact teacher，不运行 P2–P4 中的 contact addon。

#### F4 — Fold/source/reliability 不稳定

若 pooled 方向为正，但不满足 fold 稳定性或 source/reliability strata 差异过大，V2.21-C 使用第 8 节 outer-fit-only 方差权重。source/reliability 仅用于采样、权重和审计，禁止进入 model input。

#### F5 — Scalar 相关改善但 Top5 不改善

若 Rdual Spearman/MAE 明显改善，但 EF5/hits 未达增量门，V2.21-D 保留 calibrated R8/R9 heads，新增独立 Top-K rank head，使用 P4 的 parent-balanced LambdaLoss。ranking logit 只能排序，不得冒充 Rdual。

---

## 4. P1：Contact causal ablations

### 4.1 目的

判断 V1.3 的增量是否真正来自 residue-contact 和固定 PVRIG target/conformer 信息，而不是随机正则化、位置先验或 source shortcut。

### 4.2 固定项目

1. contact-label shuffle 五折配对重训；
2. V4D-only 五折诊断；
3. target-residue embedding 固定 permutation；
4. 8X6B/9E6Y conformer swap；
5. score-parent contact evaluator，对真实 contact、position-only baseline 和 shuffle 进行配对比较。

### 4.3 P1 通过要求

- true-contact evaluator 相对 position-only baseline 的 paired whole-parent bootstrap 95% CI 下界大于 0；
- contact-label shuffle 相对 C0 不得获得显著正增量，且其 EF5 增量不得超过真实 contact 增量的 50%；
- target-residue permutation 必须使 heldout contact 主指标相对下降至少 10%，且 scalar EF5 至少下降 0.10；
- conformer swap 必须使 receptor-specific mean MAE 相对恶化至少 2%；
- V4D-only 只作 source 敏感性诊断，不能单独挽救其他失败门。

任一 causal gate 失败：

```text
STOP_NO_CONTACT_PROMOTION
```

不启动 P2，不把 contact 输出输入 P3/P4。

---

## 5. P2：Multi-seed 与不确定性

### 5.1 固定运行

- seeds：`43 / 917 / 1931`；
- 每个 seed 完整 5-fold whole-parent OOF；
- 不删除坏 seed；
- 先分别平均 `R8/R9`，再取 exact min；
- 同时输出 seed std、receptor gap、Top5 rank agreement 和 fold calibration evidence。

LCB 只允许：

```text
mean_Rdual - alpha * seed_std
alpha ∈ {0.0, 0.25, 0.5}
```

alpha 只能在 inner whole-parent CV 中选择。

### 5.2 P2 晋级门

相对 strongest single-seed causal reference：

- `ΔEF5 >= 0.20`；
- `hits gain >= 10`；
- 10,000 次 paired whole-parent bootstrap 的 95% CI 下界 `> 0`；
- 至少 4/5 folds 的 `ΔEF5 >= -0.25`；
- 最差单 fold `ΔEF5 >= -0.75`；
- EF10 相对下降不超过 5%；
- Spearman 下降不超过 0.03；
- MAE 恶化不超过 10%。

P2 若完成但不晋级，可继续 P3，但 P3 不得使用 ensemble/uncertainty 特征，只能使用冻结的 strongest single-seed 证据。

---

## 6. P3：严格双层 compact stack

### 6.1 基础模态

主 stack 固定为：

```text
L1 = V2.13 top-weighted target-conditioned model
B  = clean target-attention reference model
M2 = label-free VHH monomer structure model
C2 = label-free dual-receptor coarse-pose model
```

P1 PASS 后，可增加一个单独的 `CONTACT_ADDON` challenger；不得静默改写 B 或 L1 的定义。

### 6.2 紧凑特征

每个 base 仅允许：

- predicted R8；
- predicted R9；
- exact min；
- receptor gap；
- outer-train reference-CDF percentile。

再加入：

- 四模态 rank mean/std/min/max；
- pairwise/model disagreement；
- P2 通过时的 seed uncertainty；
- P1 通过时少量预测 contact summaries。

总维数控制在约 24–40。禁止直接输入 126D M2 raw、36D C2 raw、128D latent、candidate/parent/campaign/source ID 或任何真实 Docking pose-derived 字段。

### 6.3 真正双层 cross-fitting

对每个 outer fold：

1. outer-test parents 对所有 base/meta fitting 完全不可见；
2. outer-train 内再做 4-fold whole-parent split；
3. 每个 base 在 inner-fit 重训并预测 inner-validation，形成 outer-train meta OOF；
4. base 在全部 outer-train 重训并预测 outer-test；
5. meta-head 只在 inner-OOF features 上训练；
6. 超参数只由 inner whole-parent evidence 选择；
7. outer-test 分数只用 outer-train empirical CDF 校准，禁止在 outer-test fold 内自行 rank-normalize。

### 6.4 固定候选顺序

1. equal-rank reference；
2. non-negative linear/rank stack；
3. ElasticNet；
4. shallow HGB challenger，仅当前两者至少一项达到增量门后才允许运行。

### 6.5 P3 晋级与 P4 授权

每个 challenger 使用统一增量门。若未达到终极目标，但候选 union 的 oracle EF5 `>= 5.5`，可进入 P4；否则：

```text
STOP_INSUFFICIENT_UNION_SIGNAL
```

---

## 7. P4：Parent-balanced LambdaLoss Top-K rank head

### 7.1 设计原则

保留 calibrated R8/R9 heads，新增独立 ranking logit。ranking logit 只能用于排序，不能冒充 Rdual 或实验阻断概率。

使用固定 slate：

```text
slate_size = 256
cutoff_k   = 13  # 约 5%
```

binary relevance 只由 outer-fit global Rdual Top10 产生，不能使用 whole-dataset 或 outer-test threshold。

### 7.2 Parent-balanced hard negatives

每个 slate 的 hard negatives 固定来自：

- 50%：同 parent 的高分非 Top10 候选；
- 25%：同 reliability/CDR3-length stratum 的高分非 Top10；
- 25%：L1+B+M2+C2 union 中的全局高分 false positives。

每个 parent 设相同 cap。没有 global Top10 的 parent 只保留少量最高分 negative sentinels，不得支配 batch。

### 7.3 固定三臂

```text
T0 = scalar/reference rank head
T1 = T0 + LambdaLoss/ApproxNDCG@13
T2 = T1 + low-weight PairLogit
```

不重新运行已失败的 batch-32、TopK=4 SoftTopK 配置。P4 仍使用完整 outer/inner whole-parent cross-fitting。

---

## 8. 可靠性权重

可靠性只能作为 outer-fit loss weight，不得作为 candidate/source shortcut 输入。

多 seed 候选使用 receptor-specific empirical variance；single-seed 候选使用 outer-train multi-seed variance的第 75 百分位作为保守值：

```text
w_raw = clip((median_sigma2 + eps) / (sigma2 + eps), 0.5, 2.0)
```

随后在每个 parent 内重新归一化为 mean=1，并与冻结 sample weight 相乘。任何 variance estimate、缺失值填充和 cap 都只能在 outer-fit 内计算。

---

## 9. 统一评价、增量门和停止规则

### 9.1 主评价

```text
global true Rdual Top10
predicted budget Top5
pooled EF5 / hits / precision / recall
```

训练 AUROC、训练 loss 或随机行划分 AUROC 不能作为晋级依据。

### 9.2 统一增量门

相对该阶段 strongest causally valid reference：

- `ΔEF5 >= 0.20`；
- `hits gain >= 10`；
- 10,000 次 paired whole-parent bootstrap，95% CI 下界 `>0`；
- 至少 4/5 folds `ΔEF5 >= -0.25`；
- 最差 fold `ΔEF5 >= -0.75`；
- EF10 相对下降不超过 5%；
- Spearman 下降不超过 0.03；
- MAE 恶化不超过 10%。

### 9.3 终极门

```text
EF5 >= 5.0
hits >= 247 / 493
```

train9849 达标仍只表示 OOF computational evidence。最终声明必须由方法完全冻结后的新 prospective Docking cohort 验证。

### 9.4 顺序检验和停止

固定顺序：

```text
P1 → P2 → P3-linear → P3-ElasticNet → P3-HGB → P4-T1 → P4-T2
```

同一信息族连续三个预注册 challenger 均未获得 `>=10 hits` 且 bootstrap CI 下界 `>0` 时，立即停止调头/调损失，转向新增 independent multi-seed Docking/contact teacher。

不得：

- 结果后改阈值；
- 排除坏 fold、seed、parent 或 source；
- 从 sensitivity grid 挑最好结果；
- 把 descriptive HGB 当严格 nested 证据；
- 在任何阶段读取 sealed/open/frozen prospective rows；
- 在完整冻结和独立审查前更新 Top7500。

---

## 10. 实施前仍需完成

1. V1.3 technical recovery 与 scientific gate 正式终止；
2. 将 V1.3 valid scientific terminal（PASS 或 FAIL）的 schema/path/hash/status 写入正式 preregistration；
3. 冻结每个 base learner 的 inner/outer training contract；
4. 冻结 contact evaluator、bootstrap、LambdaLoss 和 slate sampler 实现哈希；
5. 为 split-before-access、nested parent isolation、outer-train CDF、hard-negative parent cap、可靠性 cross-fit 和 failure terminals 编写测试；
6. 独立 critic 审查 exact bytes；
7. 另写 implementation freeze 后才可启动。
