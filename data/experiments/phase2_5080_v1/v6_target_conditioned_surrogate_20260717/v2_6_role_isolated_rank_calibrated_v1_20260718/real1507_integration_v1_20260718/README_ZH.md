# V2.6 real1507 role-isolated trainer 集成 V1

## 状态

```text
FROZEN_IMPLEMENTATION_TESTED_NONLAUNCHING_CPU_ONLY
```

本包把三个已冻结接口接到同一条训练路径：

1. V2.5 real1507 数据/模型和正向输入 allowlist；
2. V2.6 独立 optimizer、分角色 clipping、contact RNG 和 kappa 梯度预算；
3. V2.6 rank/calibration V1.1：exact-min PairLogit 与 outer-train inner-OOF 校准。

本包没有 CLI、远程 launcher、Node1 任务图或正式评价器，也没有读取 outer metrics 或 V4-F/test32。

## 训练语义

模型只直接预测：

```text
R_8X6B
R_9E6Y
```

推理和 V1.1 rank 都使用：

```text
Rdual = min(R_8X6B, R_9E6Y)
```

不训练独立 `Rdual` 输出。训练中的 softmin 只保留在 scalar Huber 辅助项中，不再用于 PairLogit。

## 三条 lane

- `B_SCALAR_ATTENTION_ONLY`：scalar 参考 lane；
- `E_STRICT_DETACHED_DYNAMICS_CONTROL`：contact 只更新 contact terminal；
- `F_SHARED_GATED_CONTACT_TRANSFER`：contact 可进入 shared encoder，但 capped gradient norm 不超过 scalar shared norm 的 `kappa=0.25`。

每个可训练参数只属于一个角色；scalar optimizer 拥有 shared+attention/scalar，contact optimizer 只拥有 contact terminal。禁止全参数统一 clipping。

## Gradient accumulation

主 batch 按 `gradient_accumulation` 分窗。一个窗口内：

1. scalar loss 对实际 microbatch 数取平均；
2. 每个 scalar step 加恰好 8 个同 parent rank pairs；
3. contact loss对实际 microbatch 数取平均；
4. 执行一次 role-isolated step 和 per-role clipping。

尾部不足一个完整窗口时仍按实际窗口取平均，不沿用固定除数造成 under-scaling。

## Rank V1.1

正式训练被硬绑定到 core SHA256：

```text
b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec
```

完整 scalar train 标签进入 epoch cache，用于闭合证明；只有以下 provenance 形成 PairLogit：

```text
V4D_OPEN_MULTI_SEED
A
V4D_MULTI_SEED
MULTI_SEED
v4d_open_multi_seed_frozen_v1_1
```

V4-H A/B/C 都保持 scalar-only。旧 V1 loader 仅用于接口迁移测试，正式 dependency gate 会拒绝它。

## 校准

`fit_fold_local_calibration_from_inner_oof()` 只接受 outer-train inner-OOF 行，并显式拒绝 outer-score candidate。分别拟合受约束正斜率的 R8/R9 affine calibration，之后再计算 exact-min。

## 防火墙

- whole-parent train/score 必须严格互斥且闭合；
- score truth 不由 partition audit 或训练读取；
- neural forward 继续使用 V2.5 positive allowlist；
- M2/126D、candidate/parent/source ID、campaign 和 candidate Docking pose 不进入模型；
- V4-F/test32 access 必须为 0；
- dependency 文件全部按 SHA256 绑定。

## 验证

联合测试覆盖：

- optimizer/RNG core；
- rank/calibration V1.1 和 real1507 eligibility audit；
- integration 单元、mutation 与 CPU smoke；
- 真实 V2.5 模型的 B/E scalar/shared trajectory equality；
- strict detached 和 F shared-gated；
- 尾部 accumulation window；
- A/B/C tier mutation；
- split leakage、score-truth、legacy rank、hash mutation；
- inner-OOF calibration 和 exact-min。

Node1 CUDA/BF16 replay 尚未运行，原因和下一步见 `CUDA_REPLAY_BLOCKERS.json`。
