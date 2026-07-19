# V2.6 角色隔离 optimizer / RNG 实现 V1

## 1. 状态与边界

本目录实现 V2.6-RI-RC 的**训练动力学核心**，当前状态为：

```text
LOCAL_IMPLEMENTATION_TESTED_NONLAUNCHING
```

它没有修改正在运行的 V2.5 formal graph，没有启动远程训练，没有读取
V2.5 outer metrics，也没有访问 V4-F/test32。

证据边界保持不变：这里只是开放开发集上的 8X6B/9E6Y 计算 Docking
几何 surrogate 训练原语；不是结合概率、Kd、实验阻断、Docking Gold 或提交真值。

## 2. 已实现内容

核心文件：

```text
trainer/role_isolated_optimization_v1.py
```

实现了：

1. 三个互斥、穷尽的参数角色：
   - `shared_encoder`；
   - `attention_scalar`；
   - `contact_only`。
2. 两个无重叠 optimizer owner：
   - scalar optimizer 只拥有 shared + scalar；
   - contact optimizer 只拥有 contact-only。
3. 每个角色独立 `clip_grad_norm_`，禁止全参数 global clip。
4. `B_SCALAR_ATTENTION_ONLY` 标准 scalar step。
5. `E_STRICT_DETACHED_DYNAMICS_CONTROL`：
   - contact payload 必须已经 detach；
   - contact 梯度不得进入 shared/scalar；
   - contact loss 和 dropout 在内容定址的 `torch.random.fork_rng` 中运行；
   - context 退出后 CPU/当前 CUDA 主 RNG 必须逐字节恢复。
6. `F_SHARED_GATED_CONTACT_TRANSFER`：

```text
gC_capped = gC * min(1, 0.25 * (||gS|| + eps) / (||gC|| + eps))
gShared   = gS + 1.0 * gC_capped
```

   并记录 `||gS||`、`||gC||`、cosine、cap multiplier、最终 shared norm。
7. V2.5 orthogonal head 的结构适配器：遇到未知 trainable prefix 立即失败，
   防止未来模型改动绕开 parameter ownership gate。

## 3. 20-step 动力学等价门

测试固定相同：

- scalar/shared 初始权重；
- scalar optimizer 初始状态；
- 普通 batch；
- scalar dropout；
- 主 RNG 初始状态。

连续执行 20 个 optimizer steps，并比较：

```text
B scalar only
E contact dropout=0.5, contact loss scale=1
E adversarial contact dropout=0.2, contact loss scale=10
```

每一步都要求：

- 三条路径的 shared/scalar parameter SHA256 完全一致；
- CPU 主 RNG SHA256 完全一致；
- shared/scalar 最大绝对参数差 `<=1e-7`；
- 两条 E 路径的 contact-only 参数均发生非零更新；
- 改变 contact dropout 和 loss scale 不得改变 scalar trajectory。

## 4. Mutation tests

当前故障注入覆盖：

| Mutation | 预期结果 |
|---|---|
| 同一参数进入两个 role | fail closed |
| shared 参数同时进入两个 optimizer | fail closed |
| 使用 `GLOBAL_ALL` clip event | fail closed |
| contact dropout 在 fork 外消耗主 RNG | RNG SHA 改变并被检测 |
| E contact payload 未 detach | fail closed |
| F contact loss连接 attention/scalar terminal | fail closed |

## 5. 本地验证

在仓库根目录执行：

```bash
D=experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/\
v2_6_role_isolated_rank_calibrated_v1_20260718/implementation_v1_20260718

python3 -m py_compile \
  "$D/trainer/role_isolated_optimization_v1.py" \
  "$D/tests/test_role_isolated_optimization_v1.py"

python3 -m unittest discover -s "$D/tests" -p 'test_*.py' -v
sha256sum -c "$D/SHA256SUMS"
```

冻结时结果：

```text
13 tests
OK
```

## 6. 尚未实现、不得越界声称

本 V1 只是单 optimizer-step 的训练内核。以下仍属下一阶段：

- 把 scalar/contact forward 拆分接口接入真实 1,507 行训练 runner；
- gradient accumulation window 的正式 runner 级闭合；
- `ParentPairEpochCache` 与 noise-aware rank loss；
- fold-local affine calibration；
- nested whole-parent V2.6 pilot；
- 4x4090 远程训练。

这些未完成项不能由当前 13 个局部测试替代。
