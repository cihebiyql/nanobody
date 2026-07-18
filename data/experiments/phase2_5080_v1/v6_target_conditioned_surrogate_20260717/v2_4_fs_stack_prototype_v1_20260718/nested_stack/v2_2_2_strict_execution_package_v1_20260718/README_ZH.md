# V2.2.2 strict nested-stack 执行包 V1

本目录封装 V2.2.2 的严格 double whole-parent cross-fit 计划，用于在 Node1 上生成序列模型与 Docking 连续几何目标之间的 open-development surrogate 证据。

## 当前状态

```text
PASS_AUDITED_DRY_RUN_NOT_AUTHORIZED_NOT_LAUNCHED
```

- 不启动训练；
- 不读取 sealed evaluation/test32；
- 不读取预测指标；
- 当前 ready manifest 明确为 `production_authorized=false`；
- GPU job 的 `command` 必须为 `null`，因此该包不能被直接执行。

## 数据闭环

- 总监督集：1507 条；
- V4D open multi-seed：226 条；
- V4H Stage 1 可分析：1281 条；
- V4H Stage 1 排名表：1320 条，其中 39 条技术不完整；
- Stage 2 选中：384 条；
- 已验证 V4H 训练子集与 Stage 1 的 1281 条 `DUAL_1_SEED` 候选完全一致。

Stage 2 的 384 条目前是后续 adaptive Docking 证据，不会在本 V2.2.2 冻结包中事后加入或修改既有 1507 条训练集。

## 主模型及资源

主 stack 每条候选使用 6 个输入：

```text
M2_R8, neural_R8, contact_score_R8,
M2_R9, neural_R9, contact_score_R9
```

共 5 个参数：两个 receptor intercept，以及 M2/neural/contact 的三个共享非负斜率。主目标为：

```text
R_dual_min = min(R_8X6B, R_9E6Y)
```

固定 lane：

| lane | marginal | pair | Node1 GPU |
|---|---:|---:|---:|
| B_TARGET_NO_CONTACT | 0.0 | 0.0 | 2 |
| C_SPLIT_MARGINAL | 1.5 | 0.0 | 4 |
| D_SPLIT_PAIR | 1.0 | 0.5 | 5 |

DAG 总计 195 jobs：

- inner GPU training：75；
- outer-train refit GPU：15；
- CPU 证据组装、验证、meta fit 和 materialize：105。

Node1 规划路径：

```text
/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_package_v1_20260718
/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_v1_20260718
```

## M2 + C2 challenger

M2 + C2 严格 double-cross-fit challenger 已有独立完成证据，其结论为：

```text
DO_NOT_PROMOTE_M2_C2_STACK
```

因此它仅作为独立 challenger 证据绑定，不加入主 195-job DAG，也不事后重跑。

## 构建与审计

```bash
python build_v2_2_2_strict_nested_package_v1.py --output-dir <new-directory>
python audit_v2_2_2_strict_nested_package_v1.py --package-root <new-directory>
```

只有在独立审计完成且生成新的、显式的、versioned production authorization 后，才能另行生成可执行 graph。不得修改本包的 ready manifest 或当前 dry-run graph 伪造授权。
