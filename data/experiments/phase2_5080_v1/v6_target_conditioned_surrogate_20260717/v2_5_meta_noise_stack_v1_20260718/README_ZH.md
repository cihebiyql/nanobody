# V2.5 Meta / Noise Strict Cross-Fit 实现

## 状态

```text
BUILD + TEST + CANONICAL DRY-RUN COMPLETE
FORMAL META PERFORMANCE NOT RUN HERE
V4-F / test32 ACCESS = 0
```

本目录实现下一代 `V2.5-ORTHO-CONTACT-POSE-STACK` 的 CPU/meta/data-contract
部分。它只逼近独立 8X6B/9E6Y Docking 的连续计算几何，不表示结合、Kd、
实验阻断、Docking Gold 或提交真值。

## 已实现

### 1. Primary：M2 fallback convex residual stack

```text
prediction_t = M2_t
             + wN * (Neural_t - M2_t)
             + wC * (Contact_t - M2_t)
             + wP * (C2_t - M2_t)

wN,wC,wP >= 0
wN+wC+wP <= 1
```

- R8/R9 共用三项权重；
- 不使用自由 intercept；
- 固定 L2 把新增分支收缩回 M2；
- `R_dual_min` 始终由预测 R8/R9 的 exact min 得到。

### 2. Strict double whole-parent cross-fitting API

`run_strict_outer_crossfit()` 要求：

- 五个 outer fold 均存在；
- 每个 outer-test candidate 仅出现一次；
- meta-head 仅拟合 outer-train 的 inner whole-parent OOF base evidence；
- inner/outer candidate 和 parent 均不重叠；
- outer-test truth 不进入 fit、scaling、noise 或 GBDT。

### 3. C2 fold-local 接口和现有 OOF 接入

- `fit_fold_local_pca8_ridge()` 的 fit API 只接受 train rows；
- score rows 无法参与 standardization、constant filtering、PCA8 或 Ridge；
- alpha 只由 inner OOF 选择，`1e-12` 平局取最大 alpha；
- 现有 1,507 条 C2 outer OOF 经 `candidate_id + frozen outer_fold` 闭合；
- outer C2 选择的 alpha 为 fold 0/1/2 = 100，fold 3/4 = 10；
- `attach_existing_c2_outer_oof()` 将其接到 outer base evidence；inner C2
  仍必须在对应 inner-train 内重算，不能用全体 OOF 代替。

### 4. A/B-only measurement-noise head

- 只把有真实重复 seed 的 Tier A/B 当作 `seed_dispersion_max` 真值；
- Tier C 缺重复永远不解释为零方差；
- 目标为 `log(dispersion^2 + 1e-6)`；
- 固定 Ridge alpha = 10；
- reliability 为训练折内参考方差除以预测方差，再截断至 `[0.25,4.0]`；
- inner meta-fit 使用再次 whole-parent cross-fitted 的 reliability；
- outer score reliability 只由全部 outer-train A/B 拟合。

### 5. Shallow GBDT challenger

固定为 challenger，不是 primary：

```text
HistGradientBoostingRegressor
depth=2
trees=64
learning_rate=0.05
min_samples_leaf=64
l2=2.0
```

输入只有 18 个低维 OOF evidence/branch disagreement 特征和一个
cross-fitted predicted reliability。禁止 candidate/parent/campaign/source/fold/seed
ID、原始 latent 以及候选 Docking pose-derived 输入。

## Canonical dry-run 结果

权威 receipt：

```text
prepared/protocol_dry_run_v1_1/DRY_RUN_RECEIPT.json
```

验证结果：

```text
1,507 candidates
31 whole-parent clusters
5 outer folds
5 inner folds per outer
A/B/C = 349 / 241 / 917
C2 candidate scored exactly once = true
C2 exact-min violations = 0
same-parent leakage = false
V4-F/test32 access = 0
performance metrics computed = false
formal training launched = false
```

`protocol_dry_run_v1` 是严格五折 API 和 GBDT uncertainty feature 接入前的
开发 dry-run；当前权威版本为 `protocol_dry_run_v1_1`。

## 运行

```bash
ROOT=experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/v2_5_meta_noise_stack_v1_20260718
PY=experiments/phase2_5080_v1/.venv-phase2-5080/bin/python

$PY -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v

$PY "$ROOT/src/dry_run_v1.py" \
  --contract "$ROOT/CONTRACT_V1.json" \
  --output-dir "$ROOT/prepared/protocol_dry_run_v1_1"
```

## 下一步依赖

该实现不自行启动 GPU base model。正式 meta evaluation 需要 V2.4 strict nested
runtime 输出完成并同步：

1. 每个 outer fold 的 B/C/D inner OOF evidence；
2. 每个 outer fold 的 B/C/D outer-test evidence；
3. 将 inner/outer C2 fold-specific evidence接入；
4. 在本目录冻结实现哈希后运行五折 `run_strict_outer_crossfit()`；
5. primary、reliability challenger、GBDT challenger 分开报告，V4-F 继续 sealed。

