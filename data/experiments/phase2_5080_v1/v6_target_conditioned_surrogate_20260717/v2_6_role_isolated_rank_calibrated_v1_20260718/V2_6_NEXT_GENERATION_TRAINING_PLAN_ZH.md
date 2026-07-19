# V2.6 ROLE-ISOLATED / RANK-CALIBRATED 下一代训练方案

## 0. 结论

V2.6 不应继续叠加 D_FULL_PAIR 的层数，也不应先换 ESM2-3B。当前更值得修正的是**训练动力学、排序目标与校准闭环**：

```text
frozen ESM2-650M + VHH/target graphs
        ↓
shared encoders
        ├── attention/scalar task: direct R8/R9
        └── calibrated contact task: pair/marginal evidence

strict per-role optimizer ownership + per-role clipping
        ↓
Huber scalar calibration + noise-aware within-parent rank loss
        ↓
fold-local positive affine scalar calibration
        ↓
M2 + C2 + low-dimensional neural/contact evidence
        ↓
strict nested constrained stack; exact Rdual=min(R8,R9)
```

建议命名：

```text
V2.6-RI-RC
ROLE-ISOLATED / RANK-CALIBRATED
```

V2.6 只近似独立 8X6B/9E6Y Docking 的连续计算几何；它不是 binding、Kd、实验阻断、Docking Gold 或提交真值。

---

## 1. 相对 V2.5 的可证伪问题

### 1.1 Detached 仍有间接训练耦合

V2.5 `E_DECOUPLED_CONTACT_DETACHED` 已经将 contact 输入的 encoder state `detach()`，所以 contact loss 没有直接反向路径进入 shared encoder。但当前训练器仍然：

```text
scalar loss + contact loss
→ one backward
→ clip_grad_norm_(all trainable parameters)
→ one AdamW.step()
```

因此 contact-only 梯度范数会改变全局 clip scale，间接改变 scalar/shared 更新。`Detached` 只是 no-direct-autograd，不是 dynamics-independent control。

### 1.2 当前 scalar loss 更关注绝对值，未显式优化比赛前筛所需的同 parent 排序

V2.5 主损失是 R8/R9 SmoothL1 和 softmin dual SmoothL1。它对 MAE/RMSE 有利，但不能保证同 parent 设计兄弟之间的次序。过去已经出现“Spearman 上升但 MAE/RMSE 变差”，所以下一版必须将排序和校准同时约束，而不是只换一个 loss。

### 1.3 Contact score 还不是校准概率

balanced BCE 在 candidate/receptor 内重新平衡正负质量，会改变有效 prevalence。因此直接 `sigmoid(logit)` 仅能称为 contact score，不能称为接触概率。

### 1.4 重复 seed 已有数据，但尚未先量化 teacher noise ceiling

开放监督共 1,507 条 / 31 个 whole-parent clusters：

- V4-D multi-seed：226；
- V4-H adaptive：1,281；
- 当前预期重复分层：A/B/C = 349/241/917。

其中 A/B 可以估计测量噪声，但 V4-H 的补 seed 是根据首 seed 排名自适应选择，对高分区偏重。因此它可用于诊断，不能直接支持无偏 candidate-specific reliability weighting。

---

## 2. V2.6 架构与 lane

### 2.1 共享表征，独立 terminal

保留 V2.5 已正确实现的结构：

```text
shared VHH/target representation
        ├── attention projections + attention terminal
        └── contact projections + contact terminal + calibration
```

attention logits 只用于双向路由，contact logits 只用于 pair/marginal 监督和显式证据导出。contact probability/summary 不反馈进 scalar head。

### 2.2 固定三个 lane 角色

1. `B_SCALAR_ATTENTION_ONLY`
   - 无 contact module；
   - 直接 R8/R9；
   - 是 scalar 干净基线。

2. `E_STRICT_DETACHED_DYNAMICS_CONTROL`
   - contact 读取 detached encoder state；
   - scalar/shared 与 contact-only 由两个不重叠 optimizer 所有；
   - 分别 clip，分别 step；
   - 同 seed、同 batch order、同 scalar 初始权重下，scalar/shared 更新必须与 B 动力学等价。

3. `F_SHARED_GATED_CONTACT_TRANSFER`
   - 是 V2.6 的正式 neural primary；
   - scalar optimizer 唯一拥有 shared encoder + attention/scalar 参数；
   - contact optimizer 唯一拥有 contact terminal/calibrator；
   - contact 对 shared encoder 的梯度以 task gradient 形式手工合并，不得由第二 optimizer 重复拥有 shared parameter。

B 和 E 是诊断，F 的主角色必须在 formal outer 结果前冻结，不得看结果后在 lane 中挑最佳。

---

## 3. Optimizer ownership 和梯度规则

### 3.1 参数角色

```text
P_shared  = AA/region embeddings + VHH graph + target graph + conformer embedding
P_scalar  = attention projections/terminal + condition fusion + scalar head
P_contact = contact projections/terminal + contact temperature/bias calibrator
```

所有 trainable parameter 必须恰好归属一个 optimizer owner。禁止 overlapping optimizer ownership。

### 3.2 Strict Detached

```text
optimizer_scalar(P_shared, P_scalar)
optimizer_contact(P_contact)

shared/scalar forward using the main scalar RNG stream
backward(L_scalar)
clip(P_shared, clip_shared)
clip(P_scalar, clip_scalar)
optimizer_scalar.step()

contact forward/backward inside an isolated contact RNG stream
using detached shared states
clip(P_contact, clip_contact)
optimizer_contact.step()
```

预注册初始值：

```text
clip_shared = 1.0
clip_scalar = 1.0
clip_contact = 1.0
```

梯度累积时两个 optimizer 必须在各自 accumulation window 结束时独立校正和 step。

仅分开 optimizer 和 gradient clip 还不足够。如果 contact dropout/augmentation 消耗 PyTorch 全局 RNG，后续 scalar dropout mask 仍会与 B 不同。V2.6 因此冻结以下 RNG 隔离：

```text
1. scalar/shared forward 只使用主 RNG 流；
2. contact-only forward 必须放在
   torch.random.fork_rng(devices=[current_cuda_device]) 内；
3. 进入 context 后使用内容定址种子：
   SHA256(base_seed, outer_fold, inner_fold, epoch,
          optimizer_step, accumulation_microstep, "contact_rng")；
4. 只在 forked context 内设置 CPU/CUDA contact seed；
5. 离开 context 时由 fork_rng 恢复 CPU 和当前 CUDA
   的主 RNG state；
6. contact 模块不得在 forked context 外调用任何随机操作。
```

E strict-detached 复用 scalar forward 产生的 shared states，然后对它们 `detach()`；不为 contact 重放一次含 dropout 的 encoder。F shared-gated 也复用同一 shared-state computation graph，但 contact terminal 自身的随机层仍在 contact RNG context 中运行。

**必须测试**：将 B 和 E 的 shared/scalar state 对齐，为 E 故意启用 `p=0.5` contact dropout 和非零 contact loss，连续至少 20 个 optimizer steps：

- 每步 scalar forward 前后的 CPU/CUDA 主 RNG state SHA 必须与 B 一致；
- 每步 shared/scalar parameter SHA/maximum absolute delta 必须一致，容差不高于 `1e-7`；
- E 的 contact-only parameter 必须发生非零更新；
- 将 contact dropout 从 0.5 改为 0.2 或将 contact loss 放大 10 倍，不得改变 shared/scalar trajectory。

任一项失败，E 不能称为 strict dynamics control。

### 3.3 Shared-gated contact transfer

对 `P_shared` 分别计算：

```text
gS = grad(L_scalar,  P_shared)
gC = grad(L_contact, P_shared)
```

使用固定梯度预算而不是自由相加：

```text
gC_capped = gC * min(1, kappa * (||gS|| + eps) / (||gC|| + eps))
g_shared  = gS + lambda_contact_shared * gC_capped
```

首个 formal 版本建议冻结：

```text
kappa = 0.25
lambda_contact_shared = 1.0
final shared clip = 1.0
```

记录每步 `||gS||`、`||gC||`、cosine(gS,gC)、cap 比例和最终 shared norm。PCGrad/GradNorm 只作后续 challenger，不在第一个 V2.6 formal primary 中同时引入，避免将多个变量混在一起。

---

## 4. Scalar 目标：校准 + 排序

### 4.1 直接目标与 exact-min

模型只直接输出：

```text
R8_hat, R9_hat
```

训练使用 FP32 normalised softmin auxiliary；推理和所有对外结果使用：

```text
Rdual_hat = min(R8_hat, R9_hat)
```

禁止独立 Rdual 自由输出。

### 4.2 损失

```text
L_scalar = 1.00 * L_Huber(R8,R9; beta=0.03)
         + 0.50 * L_Huber(softmin_tau(R8,R9), true_Rdual; tau=0.02)
         + 0.10 * L_within_parent_pair_rank
```

Huber 负责绝对标度，pair-rank 只负责可重复噪声以外的顺序。第一个 V2.6 formal primary 不加 batch-moment/CCC 损失：它们对 parent-grouped batch 的组成过于敏感，且与下文 fold-local affine calibration 功能重叠。

### 4.3 Noise-aware within-parent pair rank

只在同 parent 内构造 pair；parent ID 只用于 sampler/loss grouping，绝不作模型输入。训练期间的预测 dual 必须是可微 softmin，不能在 rank loss 中使用 exact min：

```text
ydual_i = exact_min(y8_i, y9_i)                  # frozen teacher definition
pdual_i = normalised_softmin_tau(p8_i, p9_i)    # differentiable, tau=0.02
d_y = ydual_i - ydual_j
d_p = pdual_i - pdual_j
L_pair = softplus(-sign(d_y) * d_p / tau_rank)
```

exact min 只用于 inference、预测冻结和指标报告。

规则：

- 主排序目标为 `Rdual=min(R8,R9)`；
- `|d_y| < delta_noise` 的 pair 丢弃，防止强迫模型学习 teacher 可重复性范围内的随机顺序；
- 每个 parent 每 epoch 最多固定数量 pair，防止大 sibling family 主导；
- pair 权重为 `min(|d_y|/delta_noise, 3)`；
- `tau_rank=0.03`；
- `delta_noise` 必须由预先完成的 repeat-seed 诊断按固定公式得到，然后在训练前冻结。

预注册公式：

```text
delta_noise = clip(
    median_candidate(MAD_seed(Rdual)) * 1.4826 * sqrt(2),
    0.01,
    0.03
)
```

#### 4.3.1 独立 parent-pair epoch cache

不允许从普通 `batch_size=8` candidate batch 中“顺便找同 parent pair”。随机 batch 可能几乎没有 sibling pair，使预注册的 rank loss 在实际中变成近似零。

V2.6 每个 epoch 必须为当前 outer/inner-train partition 单独建立 `ParentPairEpochCache`：

```text
for each training parent:
    enumerate unordered candidate pairs
    keep abs(true_Rdual_i-true_Rdual_j) >= delta_noise

deterministic seed = SHA256(
    base_seed, outer_fold, inner_fold, epoch, "rank_pair_cache"
)

balanced parent round-robin sampling
→ exactly number_of_scalar_optimizer_steps * 8 pair records
→ 8 pair records per scalar optimizer step
```

冻结规则：

- `scalar_candidate_batch_size=8`；
- `rank_pair_batch_size=8 pairs`，与 candidate batch 独立；
- rank-eligible parent 定义为至少拥有 1 个通过 `delta_noise` 的 pair；零 eligible-pair parent 只记录、不伪造顺序监督；
- 当前 train partition 少于 8 个 rank-eligible parents 时 fail closed；
- 每个 rank pair batch 尽可能来自 8 个不同 parent；
- parent 以 round-robin 方式暴露，每 epoch 的 pair count 最多相差 1；
- 同一 parent 内的 eligible pair 先无放回打乱，只有数量不足时才在耗尽后确定性循环；
- 将 8 个 pair 的去重 endpoint 打包成一个 scalar-only forward，不为 rank pass 计算 contact head；
- 每个 scalar optimizer step 同时使用一个普通 8-candidate batch 和一个 8-pair rank batch，共用一次 scalar optimizer step；
- pair loss 先在 parent 内平均，再在 parent 间平均；
- cache 仅可读取当前 train partition truth，禁止 validation/outer-test 候选出现。

每 epoch 持久化 cache TSV 或内容定址 JSON，并记录：总 pair 数、每 parent pair 数、零 eligible-pair parent 列表、重复比例、被丢弃的 noise-margin pair 数、candidate/split/label hash。任一 scalar step 没有恰好 8 个有效 rank pairs 必须 fail closed，不能静默返回零 rank loss。

### 4.4 Fold-local positive affine scalar calibration

为减少“排序变好但绝对误差变差”，每个 outer fold 只用 outer-train 的 strict inner-OOF neural prediction 拟合：

```text
R_r_cal = a_r * R_r_raw + b_r
a_r in [0.5, 1.5]
b_r in [-0.10, 0.10]
```

用 Huber(beta=0.03) + identity shrinkage：

```text
0.10 * ((a_r-1)^2 + b_r^2)
```

两个 receptor 可有不同 `a,b`，但外层 test 不得用于拟合、重标定或选择。校准后再取 exact min。

---

## 5. Attention temperature 政策

当前 pair terminal 本身可改变 logit scale，若再自由学习 temperature，两者在数值上不可识别，容易以饱和换取表面的 attention 尖锐度。

V2.6 primary 因此固定：

```text
tau_attention_8X6B = 1.0
tau_attention_9E6Y = 1.0
trainable = false
```

允许一个**诊断 challenger**在 inner whole-parent CV 比较 shared fixed temperature `{0.5, 1.0, 2.0}`，但不得根据 outer 结果切换 primary。不启用 receptor-specific learned temperature。

若未来必须学习 temperature，先要：

1. 强制 attention terminal 单位范数；
2. 将 temperature 约束在 `[0.5,2.0]`；
3. 只允许双 receptor 共享一个 temperature；
4. 加 `log(tau)^2` 正则；
5. 预注册 attention entropy/saturation gate。

在此之前，学习 temperature 不纳入 formal primary。

---

## 6. Contact 校准

### 6.1 表征训练

保留 balanced soft BCE 训练 contact representation，但输出命名必须是 `contact_score`，不是 `contact_probability`。

### 6.2 概率校准

每个 receptor 使用独立但低自由度的 affine-temperature calibration：

```text
p_ij_r = sigmoid(logit_ij_r / T_r + b_r)
T_r in [0.25, 4.0]
b_r in [-6, 6]
```

校准器只在 outer-train 的 inner-OOF contact logits 上使用**原始 prevalence、非 balanced BCE**拟合，主校准集为 Tier A，Tier B 以 0.5 权重加入，Tier C 不用于概率校准。outer-test 不得重拟合。

校准后再计算低维证据：

- hotspot mass 8/9；
- interface specificity 8/9；
- CDR1/2/3 mass；
- pair entropy 8/9；
- dual hotspot minimum；
- conformer gap。

formal primary meta 最多使用预先列明的 12 个 contact summary，禁止把原始 pair map 或高维 latent 交给 GBDT。

### 6.3 Contact 评估

按 receptor 和 Tier A/B 分层报告：

- Brier score；
- log loss；
- expected calibration error（固定 10 bins）；
- AUPRC 及 prevalence baseline；
- hotspot/interface/CDR summary 的 seed 稳定性。

若校准后 Brier/ECE 不改善，formal meta 使用未校准 score 的方案也只能作事先冻结的 diagnostic，不得事后切换。

---

## 7. Repeat-seed reliability 和 noise ceiling

### 7.1 必须在 V2.6 训练冻结前完成的诊断

候选为统计单位，seed 不得当作独立训练行。对 R8/R9/Rdual 分别计算：

1. 各 seed pair 的 Spearman/Pearson；
2. ICC(1,1) 和 bootstrap CI；
3. Spearman-Brown `k`-seed aggregate reliability；
4. `sqrt(reliability_k)` 作为 classical-error 假设下的相关上限参考；
5. 单 seed 对其余 seed 均值/中位数的 empirical ceiling；
6. candidate 内 SD/MAD/IQR；
7. 按首 seed high/mid/low、source、parent、patch、design mode 的条件方差。

V4-D 和 V4-H adaptive repeats 分开报告，不用一个汇总数掩盖选择偏差。

### 7.2 Reliability 在 V2.6 中的用法

由于 V4-H 重复集是自适应抽样，V2.6 formal primary：

- 用 repeat noise 设定 `delta_noise`；
- 报告 noise-normalized error 和 ceiling gap；
- scalar 损失按 source → parent → candidate 分层平衡，A/B/C 不再使用事先猜测的不同可靠性权重；
- 不使用自由 candidate-specific inverse variance。

formal scalar 权重：

```text
Tier A = 1.00
Tier B = 1.00
Tier C = 1.00
```

接触监督仍按 A/B/C 质量分层，但不影响 scalar 标签权重。已经看到当前 reliability stack 没有稳定改善，因此不允许用更复杂的 noise head 取代 primary。

### 7.3 无偏 sentinel

下一批冻结 150 条 sentinel：

- 首 seed high/mid/low 各 50；
- 各层内覆盖 parent/patch/mode/CDR3 length；
- 在补 seed 之前冻结 candidate ID 和 SHA256；
- 无论第一/第二 seed 表现如何，都完成固定三 seed 双 receptor。

在该 sentinel 闭合前，candidate-specific heteroscedastic noise head 和 inverse-variance primary weighting 都不晋级。

---

## 8. Meta 融合

V2.6 仍然保持正交分支：

```text
M2 126D Ridge
C2 coarse-pose
F_SHARED_GATED scalar R8/R9
calibrated low-dimensional contact summaries
→ strict double cross-fitting
→ constrained linear stack
→ exact min
```

Primary 先使用强收缩线性模型，不使用原始 latent：

```text
pred_r = M2_r
       + wF * (F_r  - M2_r)
       + wC * (C2_r - M2_r)
       + beta^T z(contact summaries)
```

约束：

- `wF,wC >= 0`；
- `wF+wC <= 1`；
- contact 系数使用 group L2 强正则；
- no intercept，M2 精确 fallback 必须可重现；
- 所有 scaler、contact calibration、scalar calibration 和 meta fit 都只在 outer-train inner-OOF 上进行。

shallow HistGBDT/LightGBM 仅作预注册 challenger：`depth<=3`、large min leaf、少量树、无 ID/source/fold 特征。它不能在 linear primary 失败后事后接替。

---

## 9. 是否换 ESM2-3B 或更强 structure encoder

### 9.1 Frozen ESM2-3B

当前不作 primary。只有以下条件全部满足后才启动 paired challenger：

1. V2.6-650M 通过 target/contact 消融，证明模型确实使用 PVRIG 而非 parent shortcut；
2. repeat-seed aggregate ceiling 比当前 best whole-parent rho 至少高 0.05；
3. 650M 版在 inner whole-parent 呈现稳定欠拟合，而不是训练好、外层坏的过拟合；
4. 3B embedding 预计算一次并 hash 冻结，后续架构、split、seed、projection dimension 与 650M 严格配对；
5. 只在 inner whole-parent CV 进行 650M/3B 比较，不用 outer 选择 PLM。

如果这些条件不成立，换 3B 只是增加显存和过拟合自由度。

### 9.2 Structure encoder challenger

M2 长期强于 neural branch，说明 label-free 单体几何是重要信号。因此在 V2.6 基线闭合后，小型 GVP/EGNN 结构编码器 challenger 比盲目换 3B 更有优先级，但必须：

- 只读取 label-free VHH monomer 节点/边/坐标和固定 target graph；
- 不读 126D M2、ID 或 candidate Docking pose；
- 参数量不高于当前 head 的 2 倍；
- 与现有 invariant graph encoder 做配对 whole-parent inner CV；
- 必做 coordinate/edge ablation，且两个 teacher source 都要有同方向增益。

粗姿势 C2 仍作独立 meta 证据，不送进 neural branch，以保留增量可归因性。

---

## 10. Formal 消融

所有消融都使用同一 whole-parent outer/inner split，并在读取 outer truth 前冻结预测。

### 10.1 训练动力学

- B vs E strict-detached scalar parameter trajectory equivalence；
- global clipping 旧行为重现（diagnostic only）；
- F shared-gated 的 `kappa=0.25` vs no-contact-gradient。

### 10.2 Loss

- `lambda_rank=0` vs frozen `0.10`；
- fold-local affine calibration identity vs fitted positive affine。

### 10.3 Target/contact 依赖

- hotspot mask shuffle；
- interface/off-interface mask swap；
- 8X6B/9E6Y conformer swap；
- target residue node-feature permutation（固定图拓扑）；
- contact-label donor shuffle（在 receptor/tier/source 内保持 prevalence）；
- contact calibration identity vs fold-local calibrated；
- contact summaries 从 meta 移除。

### 10.4 Shortcut 和结构

- VHH-only；
- CDR3-only；
- parent/scaffold-only diagnostic baseline；
- VHH coordinates/edges ablation；
- M2-only 和 M2+C2。

声称 target-conditioned 所需的最低消融效果：目标信息破坏后 Rdual Spearman 平均降低至少 0.02，且至少 4/5 outer folds 同方向。

声称 contact-transfer 所需的最低效果：F 相对 E strict-detached 的 Rdual Spearman 提升至少 0.01，且 paired-parent bootstrap 95% CI 下界大于 0。否则 contact 只能作显式证据，不能声称它改善了 scalar encoder。

---

## 11. 评估与 promotion gate

保留当前严格 gate，不因 V2.5/V2.6 结果修改：

- Rdual Spearman `>= 0.6194011215999979`；
- Rdual MAE `<= 0.0323587150283071`；
- Rdual RMSE `<= 0.04290748546218935`；
- V4-D/V4-H 各自 MAE 不劣化，各自 delta Spearman 不为负；
- parent-macro Rdual MAE 不劣化；
- 至少 16/31 parents 的 Rdual MAE delta 非负；
- paired whole-parent bootstrap delta Spearman 95% CI 下界 `>0`；
- R8/R9 Spearman 相对 M2 都不低于 `-0.03`；
- exact-min 违规 0；
- 1,507 candidates / 31 parents / 5 outer folds 闭合；
- V4-F/test32 在预测冻结前 access count = 0。

新增诊断指标：

- within-parent Rdual Spearman/NDCG；
- scalar calibration slope/intercept；
- R8/R9/dual 相对 noise ceiling 的 gap；
- contact Brier/ECE/AUPRC；
- attention entropy/saturation；
- scalar/contact/shared 梯度范数和冲突率。

formal primary 任一 gate 失败，结论必须是 `DO_NOT_PROMOTE`，精确回退到 M2。不得用消融、GBDT、更大 PLM 或某一个好看的 seed 事后接替。

---

## 12. 停止规则

满足任一条就停止扩大模型，转而改善 teacher 或数据设计：

1. noise ceiling 与当前 best whole-parent rho 差小于 0.05；
2. target/contact ablation 不使模型稳定退化；
3. F shared-gated 不超过 E strict-detached，说明 contact encoder transfer 没有证据；
4. 排序增益依赖 MAE/RMSE 明显劣化，且 fold-local calibration 不能修复；
5. 增益只存在一个 teacher source 或少数 parent；
6. 3 个 refit seed 的方向不一致；
7. structure/3B challenger 只降低训练误差，不改善 whole-parent inner validation。

---

## 13. 建议执行顺序

### Phase 0：诊断冻结

1. 完成 repeat-seed reliability/noise ceiling；
2. 冻结 `delta_noise`、tier weights 和 ceiling stop rule；
3. 建立 B/E 动力学等价回归测试。

### Phase 1：最小实现

1. 独立 optimizer ownership + per-role clip；
2. F shared gradient budget telemetry；
3. rank/calibration loss；
4. fold-local scalar/contact calibration；
5. 预测导出保存低维 contact summary 和不确定性。

### Phase 2：inner-only pilot

1. 单个预指定 outer-train 分区运行 B/E/F；
2. 验证梯度、exact-min、校准、rank pair closure；
3. 只用预注册的两个有限 challenger，不做无界调参。

### Phase 3：formal nested

1. whole-parent 5 outer x inner CV；
2. B/E diagnostic，F primary；
3. 每个 outer 分区三 refit seeds；
4. 严格 inner-OOF scalar/contact calibration 和 meta fit；
5. 一次性 outer prediction freeze 后才评估。

### Phase 4：资源升级决策

1. 先判断 target/contact/structure 消融；
2. 若仍有足够 ceiling gap，先比较小型 structure encoder；
3. 只在预注册条件满足时启动 frozen ESM2-3B paired challenger；
4. 无论哪个开发 challenger 最好，V4-F/test32 都继续 sealed，直到正式生产预测完全冻结。

---

## 14. 启动前必须完成的预注册项

`PREREGISTRATION_SKELETON_V1.json` 当前是骨架，启动前必须：

1. 填写所有 input/code/split hash；
2. 写入 repeat-seed 诊断的已验证数值和 `delta_noise`；
3. 冻结 primary/challenger 角色、job graph 和 GPU 映射；
4. 冻结 formal 评估代码哈希；
5. 通过静态验证、合成测试、动力学等价测试和 fail-closed input audit；
6. 记录 `formal_outer_result_access_count=0` 与 `v4_f_test32_access_count=0`。

完成以上冻结前，不启动 V2.6 formal training。
