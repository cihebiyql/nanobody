# V2.6 outer0/inner0 八作业 Pilot 骨架 V1

## 当前状态

```text
FROZEN_NONLAUNCHING
BLOCKED_PENDING_INTEGRATION_V1_1
BLOCKED_PENDING_CUDA_SMOKE_PASS
```

本目录冻结下一轮真实训练的最小比较矩阵，但不会用已知有缺陷的
`real1507 integration V1` 启动训练。

独立复核确认 V1 尚有三个不能忽略的问题：

1. `lambda_contact_shared` 可以使 shared contact gradient 绕过 kappa 遥测；
2. calibration 还不能闭合证明 inner-OOF/三 seed ensemble provenance；
3. accumulation 当前按 microbatch 均值再平均，尚未证明等价于完整窗口的样本/层级加权目标。

因此当前产物是**可审计、不可运行的骨架**，不是伪装成 PASS 的 launcher。

## 冻结 Pilot 矩阵

固定开放开发 split：

```text
outer_fold = 0
inner_fold = 0
```

GPU 作业：

| Variant | 角色 | Seed |
|---|---|---|
| F0 shared-gated, no rank | primary | 43/97/193 |
| F1 shared-gated, V4-D exact-min PairLogit | challenger | 43/97/193 |
| B attention-only | dynamics control | 43 |
| E strict-detached | dynamics control | 43 |

共 8 个 GPU job，随后 1 个 CPU inner-validation collector。

固定资源：

```text
CUDA_VISIBLE_DEVICES=1,2,4,5
physical 1 -> cuda:0
physical 2 -> cuda:1
physical 4 -> cuda:2
physical 5 -> cuda:3
max concurrent GPU jobs = 4
one process per assigned GPU
```

## 监督和评价边界

- 只直接预测 `R8/R9`；
- `Rdual = exact_min(R8,R9)`；
- F0 的 ranking weight 为 0；
- F1 只允许 V4-D 多 seed、同 parent、超过冻结噪声 margin 的 exact-min pair；
- V4-H 只提供 scalar/contact 监督，不产生 ranking pairs；
- GPU job 不读取评价真值；
- CPU collector 只读取 outer0/inner0 的 score parents；
- 不读取 outer0 test parents，不计算 outer metrics；
- `V4-F/test32 access = 0`。

这个 pilot 只能用来决定是否值得启动完整 nested V2.6，不能作为正式 outer 结果。

## 每个 GPU job 必须交付

```text
RESULT.json
TRAINING_RECEIPT.json
STEP_EVIDENCE.jsonl
neural_head.pt
score_predictions_no_metrics.tsv
```

`RESULT.json` 必须绑定：

- 每步证据文件 SHA256 和行数；
- 行数等于 optimizer step 数；
- checkpoint SHA256；
- prediction SHA256；
- exact-min violation = 0；
- outer-test truth/metric access = 0；
- V4-F/test32 access = 0。

只存在一个 summary JSON 不足以通过 collector。

## 后续启动门

未来必须新建一个 resolved package，而不能原地修改本骨架。Resolved package 需要：

1. 精确绑定修复并复核过的 integration V1.1；
2. 精确绑定独立冻结的 CUDA driver；
3. 精确绑定 outer0/inner0 split hash 和 train-label hash；
4. 精确绑定 PASS CUDA smoke receipt；
5. 新建显式 authorization overlay；
6. 启动瞬间确认四张 4090 空闲且 `/data1 >= 100 GiB`；
7. 所有 code/input/package SHA256 重新闭合。

本目录包含 future scheduler，但 unresolved graph 中所有 `command` 均为 `null`，scheduler 会明确拒绝当前 graph。

## 本地验证

```bash
python3 -m unittest discover \
  -s inner_only_pilot_v1_20260719/tests \
  -p 'test_*.py' -v
```

然后构建不可运行包并运行静态审计：

```bash
python3 src/build_nonlaunching_inner_pilot_package_v1.py ...
python3 src/validate_inner_pilot_package_v1.py --package-root ...
```

科学边界：这里只预测独立双受体 Docking 的计算几何，不是结合、Kd、实验阻断、Docking Gold 或提交真值。
