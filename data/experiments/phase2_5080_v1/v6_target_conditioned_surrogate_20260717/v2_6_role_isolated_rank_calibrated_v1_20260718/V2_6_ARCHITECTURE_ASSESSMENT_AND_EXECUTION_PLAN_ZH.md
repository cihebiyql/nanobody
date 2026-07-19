# V2.6 下一代架构评估与执行计划

更新时间：2026-07-18

## 1. 结论

用户提出的方向总体正确，但不应再命名为新的 `V2.4-ORTHO-STACK`，因为现有实现已经演进为：

- `V2.5-ORTHO-CONTACT-POSE-STACK`：修正 attention/contact terminal 共用和独立 `Rdual` 输出；
- `V2.6-RI-RC`：进一步修正 optimizer、gradient clipping、RNG、同 parent 排序和 fold-local 校准。

下一代正式主线应为：

```text
M2 126D monomer Ridge -------------------\
C2 label-free coarse-pose ---------------+--> strict nested nonnegative stack
V2.6 F_SHARED_GATED neural/contact ------/          ↓
                                              direct R8/R9
                                                   ↓
                                       Rdual = exact min(R8,R9)
```

模型只近似独立 8X6B/9E6Y Docking 的连续计算几何，不表示 binding、Kd、实验阻断或 Docking Gold。

## 2. 对建议的逐项评估

### 2.1 Attention/contact 分头：接受，而且需要比“最后一层分开”更严格

同一 `pair_logits` 同时承担 softmax attention 和 sigmoid contact calibration，确实存在目标冲突。V2.5 已实现：

- 共享 residue/graph representation；
- 独立 attention pair projection/terminal；
- 独立 contact pair projection/terminal；
- contact score 不直接反馈到 scalar head。

但 V2.5 的 detached lane 仍使用全参数统一 gradient clipping；contact 梯度可能通过全局 clip scale 间接改变 scalar 更新。V2.6 因此必须保留：

- scalar/contact 参数唯一 optimizer ownership；
- per-role clipping；
- contact `torch.random.fork_rng` 隔离；
- B/E 连续 20 step scalar/shared 参数轨迹等价 gate；
- shared lane 的 contact gradient budget，首版 `kappa=0.25`。

### 2.2 `Rdual_min` 由 R8/R9 导出：无条件接受

正式模型只直接预测 `R8`、`R9`。训练使用 FP32 normalized softmin 辅助损失；推理、冻结预测、stacking 和报告一律：

```text
Rdual = min(R8, R9)
```

禁止独立第三输出；exact-min 误差容差为 `1e-12`。

### 2.3 OOF latent + GBDT/ranking：只接受低维、双层 cross-fitting 版本

不把 128D latent 直接送入树模型。主 meta 输入限制为低维证据：

- M2 R8/R9；
- C2 R8/R9；
- neural R8/R9；
- 2D contact composite；
- 后续版本可加入预先冻结的 14D contact summary；
- label-free QC/structure confidence；
- disagreement 和 conformer gap。

必须使用 whole-parent outer/inner 双层 cross-fitting。主 meta 仍为非负线性/ElasticNet。浅层 HistGBDT/LightGBM 只作 challenger，因为现有 strict 结果中 HistGBDT 的 Rdual Spearman 为 `0.584851`，明显低于线性 stack 的约 `0.62`。

### 2.4 监督分层：接受，但不把 adaptive repeats 当作无偏 reliability 真值

开放 scalar teacher：

- V4-D：226；
- V4-H：1,281；
- 总计：1,507 candidates / 31 whole-parent clusters。

contact/repeat tier：

- Tier A：349（V4-D 226 + V4-H 三 seed 123）；
- Tier B：241（V4-H 两 seed）；
- Tier C：917（V4-H 单 seed）。

使用原则：

- scalar R8/R9：A+B+C；
- marginal contact：A+B，C 低权重；
- full pair contact：A 主、B 次、C 不进入 full-pair 主监督；
- rank pair：只在同 parent 内，且 `|delta teacher| >= delta_noise`；
- `delta_noise=0.019614956149`，由非自适应 V4-D 三 seed 冻结得到。

V4-H repeat 是根据首 seed 排名自适应补算，不能直接训练无偏 candidate-specific variance。首版 V2.6 不把 reliability weight 混入主 scalar loss；先用 noise threshold 屏蔽不可重复 pair。

### 2.5 诊断和因果消融：必须先于 3B/更深网络

正式需要回答：模型是否真的使用 target/contact，而不是 parent shortcut。已冻结的诊断包括：

1. hotspot/interface mask swap；
2. 8X6B/9E6Y conformer payload swap；
3. target residue feature permutation；
4. within-parent contact-label donor shuffle；
5. no-contact meta evidence omission。

只有 target/contact 因果门通过，才允许声称 neural/contact 分支提供 PVRIG 条件化增量。

### 2.6 廉价 coarse pose：接受，优先级高于 ESM2-3B

C2 已出现小但跨 fold 稳定的增量：M2 的 Rdual Spearman `0.609401`，M2+C2 为 `0.617438`；说明 approach-angle proxy 有价值，但当前增量仍有限。

下一步优先扩充 label-free coarse geometry：

- VHH CDR surface point cloud；
- PVRIG interface surface；
- 低分辨率 SE(3) rigid scan；
- shape/electrostatic/hotspot proximity；
- CDR3 orientation；
- 8X6B/9E6Y joint acceptable-pose count；
- Top-K score dispersion。

这些特征不能读取候选 HADDOCK pose 或 teacher-derived Docking 输入。结构编码器 challenger 的优先级高于把 ESM2-650M 直接换成 3B。

## 3. V2.6 正式架构

### 3.1 Base branches

```text
M2: 126D label-free monomer features -> cross-fit Ridge -> R8/R9
C2: deterministic coarse-pose features -> cross-fit Ridge -> R8/R9
B: scalar attention-only diagnostic -> R8/R9
E: strict detached dynamics control -> R8/R9 + contact diagnostics
F: shared-gated contact transfer primary -> R8/R9 + contact evidence
```

Neural 分支禁止读取原始 M2 126D、parent/candidate/campaign ID 和候选 Docking pose-derived 输入。所有融合只发生在最终 OOF meta-head。

### 3.2 Loss

```text
L_scalar = 1.00 * Huber(R8,R9; beta=.03)
         + 0.50 * Huber(softmin_tau(R8,R9), true_Rdual; tau=.02)
         + 0.10 * within-parent noise-aware PairLogit
```

PairLogit：

- 每 step 恰好 8 pairs、8 个不同 parent；
- deterministic parent round-robin；
- `|delta y| < 0.019614956149` 的 pair 丢弃；
- pair weight capped at 3；
- parent ID 只用于 sampler，不进入模型输入。

Contact loss 继续按 A/B/C 分层，F lane 对 shared encoder 的 contact gradient 使用 `kappa=.25` budget。

### 3.3 Calibration 和 stacking

每个 outer fold 内：

```text
outer-train parents
  -> inner whole-parent OOF base predictions
  -> fit positive affine R8/R9 calibration
  -> fit constrained low-dimensional meta-head
  -> refit base models on all outer-train
  -> produce outer-test base features
  -> frozen calibrator/meta predict outer-test
```

禁止在同一批 OOF 行上既训练 meta 又报告 meta 性能。主 meta 为 M2-anchored nonnegative stack；GBDT 仅 challenger。

## 4. 当前已经完成的实现证据

- V2.5 301-job formal nested training 正在 Node1 GPU 1/2/4/5 运行；本次检查为 `71 completed / 4 running / 226 pending`，无 terminal，V4-F/test32 access=0。
- V2.6 role-isolated optimizer/RNG core：13/13 tests PASS，SHA closure PASS。
- V2.6 rank/calibration core：18/18 tests PASS，SHA closure PASS。
- V2.5 causal ablation nonlaunching package：12/12 tests PASS；131 jobs（85 GPU/46 CPU）已冻结但未授权启动。
- repeat-seed diagnostic：590 candidates / 3,062 receptor-seed scalars；V4-D mean-of-3 classical correlation ceiling 约 `0.936`，当前 surrogate 约 `0.62`，仍有真实改进空间。

## 5. 执行顺序

### Phase 0：收口 V2.5 正式证据

1. 等待 301/301 terminal；
2. 验证 1,507 candidates / 31 parents / 5 outer folds；
3. 验证 exact-min error=0、V4-F/test32=0；
4. 让 V1.1 strict meta evaluator 先冻结 PRETRUTH，再读取 outer truth；
5. 不在结果出来后修改本轮 stack、lane 或 gate。

### Phase 1：运行因果消融

在 V2.5 terminal 后部署冻结 131-job package，逐项判定 target/contact 依赖。消融结果只决定机制 claim 和下一代资源优先级，不回写 V2.5 promotion 结论。

### Phase 2：接入 V2.6 real1507 trainer

现在即可并行完成，不必等 V2.5 指标：

1. 将 role-isolated optimizer/RNG core 接入真实 trainer；
2. 接入 ParentPairEpochCache、PairLogit 和 positive affine calibration；
3. 增加 gradient accumulation 的分角色 step/clip；
4. 在 Node1 做真实 CUDA 20-step B/E equivalence replay；
5. 做单 fold inner-only pilot，仅检查技术闭合和训练稳定性。

### Phase 3：冻结并启动 V2.6 formal nested

在不读取 V4-F/test32 的前提下冻结：

- split/hash；
- primary F lane；
- loss weights；
- `delta_noise`；
- optimizer ownership/RNG；
- meta formula；
- promotion gates。

随后用 4 块 4090 运行 whole-parent nested formal。正式 test 只读一次。

### Phase 4：结构/coarse-pose challenger

若 V2.6 仍距 repeat-seed ceiling 很远，优先增加 label-free structure surface encoder 和改进 coarse rigid scan；必须通过严格 outer-parent OOF 才能进入 stack。

### Phase 5：条件式 ESM2-3B challenger

只在以下条件同时满足时启动：

- target/conformer/contact causal ablation 通过；
- neural 分支相对 M2/C2 有稳定独立增量；
- strict outer correlation 与 noise ceiling 仍相差至少 0.05；
- 结构/coarse-pose 增量仍不足。

首轮只使用 frozen 3B residue embeddings，不直接解冻 3B。

## 6. 正式验收线

### 技术闭合

- whole-parent split 0 leakage；
- exact-min tolerance `<=1e-12`；
- V4-F/test32 access=0；
- B/E 20-step shared/scalar trajectory max delta `<=1e-7`；
- optimizer ownership无重叠；
- contact RNG 不改变 scalar RNG；
- 1,507/31/5 closure完整。

### 预测性能

- Rdual Spearman、MAE、RMSE均报告；
- R8/R9 direct metrics均报告；
- source-specific和parent-macro均报告；
- paired-parent bootstrap 95% CI 支持增量；
- 不允许以排序改善换取明显 MAE/RMSE恶化；
- 任一冻结 gate 失败则回退到冻结 M2 或当前可证明的最强简单 stack。

### 因果/机制

- conformer swap 和 target permutation 分别要求至少 `0.01` Rdual/direct Spearman退化且parent-bootstrap下界>0；
- contact相关消融分别要求预注册 `0.005--0.01` 退化和bootstrap支持；
- 未通过时只能称为预测相关，不能称为使用了PVRIG/contact机制。

## 7. 当前决策

1. 不继续加深旧 D_FULL_PAIR；
2. 不把 raw 128D latent 交给 GBDT；
3. 不现在切到 ESM2-3B；
4. V2.6 首要工作是 real1507 trainer 集成、CUDA 动力学验证和严格 nested formal；
5. 结构/coarse-pose 是下一项最高价值信息增量；
6. 新 Docking campaign 必须加入高/中/低分、parent/patch/mode 平衡的固定多 seed sentinel。
