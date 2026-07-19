# V2.5 D-only strict meta execution adapter V1

## 目的

本目录把已经预冻结的 V2.5 `OOF latent + C2 + reliability + shallow GBDT`
方案接到 Node1 上正在运行的 V2.4 strict V1.2.1 nested cross-fit 证据。

证据边界始终是：

> 独立 8X6B/9E6Y Docking 连续几何的开放开发 surrogate；不是结合概率、
> Kd、实验阻断概率、Docking Gold 或提交证据。

## 当前授权边界

当前状态为：

```text
FROZEN_UNAUTHORIZED_INPUT_VALIDATION_ONLY
```

允许自动执行：

1. 等待上游 `TERMINAL.json`；
2. 校验 195 个上游 job result 的存在性和哈希闭合；
3. 只把 `D_SPLIT_PAIR` inner/outer base evidence 作为 V2.5 predictor 输入；
4. 校验 candidate、parent、source、fold、truth、exact-min、provenance；
5. 校验已有 C2 outer OOF closure；
6. 输出 `PASS_INPUTS_READY_UNAUTHORIZED`。

当前禁止自动执行：

- 读取或汇总正式性能结果；
- 启动 V2.5 formal evaluator；
- 把 B/C lane 作为 V2.5 predictor；
- 访问 V4-F/test32；
- 在没有单独 authorization overlay 和 runtime token 时创建正式输出。

## 冻结模型矩阵

1. `D_ONLY_FROZEN_BASE`：D neural R8/R9，dual 为 exact min；
2. `M2_C2_CONVEX`；
3. `M2_D_CONVEX`；
4. `M2_D_C2_CONVEX`：主 promotion candidate；
5. `M2_D_C2_RELIABILITY_CONVEX`：A/B 重复 seed 噪声加权 challenger；
6. `D_C2_CONTACT_RELIABILITY_HIST_GBDT`：固定浅层 GBDT challenger。

所有模型只直接预测 R8/R9，`Rdual=min(R8,R9)`，不允许第三个自由输出。

## 文件

```text
EXECUTION_CONTRACT_V1.json
EXECUTION_MANIFEST_V1.json                  # 构建后生成，仍为未授权
IMPLEMENTATION_FREEZE_V1.json               # 构建/测试后生成
src/execution_common_v1.py
src/validate_v1_2_1_strict_inputs_v1.py
src/watch_v1_2_1_terminal_then_validate_v1.py
src/build_execution_manifest_v1.py
src/dry_run_execution_adapter_v1.py
src/evaluate_authorized_v2_5_strict_meta_v1.py
tests/test_execution_adapter_v1.py
prepared/canonical_inputs_v1/
prepared/preauthorization_dry_run_v1_1/
```

`evaluate_authorized_v2_5_strict_meta_v1.py` 已实现并可测试，但当前 watcher 不会调用它。
它要求同时满足：

- runtime token SHA256；
- 单独 authorization overlay；
- overlay 精确绑定 execution manifest SHA256；
- overlay 精确绑定 input closure receipt SHA256；
- 新的空 formal output directory。

## 已验证事项

- 基础组件 17 tests；
- execution adapter 7 tests；
- canonical 1,507 候选输入哈希闭合；
- C2 五个 outer fold 的 inner replay 与冻结 alpha 完全一致：
  `100, 100, 100, 10, 10`；
- 预授权 dry-run 不打开 D outer evidence，不计算性能，不启动 formal evaluator；
- bad token 在读取 labels/runtime evidence 之前 fail-closed。

## 下一状态

Node1 watcher 只会推进到：

```text
PASS_INPUTS_READY_UNAUTHORIZED
```

之后必须由独立授权步骤创建并冻结 authorization overlay，才能运行 formal evaluation。
