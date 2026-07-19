# V2.5 ORTHO 正式 whole-parent nested 训练计划（冻结前）

## 目标与边界

用开放的 1,507 条 V4-D/V4-H Docking teacher 数据比较三条 V2.5 residue-level neural lanes：

- `B_CLEAN_TARGET_ATTENTION`
- `E_DECOUPLED_CONTACT_DETACHED`
- `E_DECOUPLED_CONTACT_SHARED`

模型只直接预测 `R_8X6B` 与 `R_9E6Y`，推理时严格使用 `min(R8,R9)` 得到 `R_dual_min`。Neural 输入禁止 M2/126D 汇总结构特征、ID、campaign 和 candidate Docking pose。输出仍是 computational Docking geometry surrogate，不是实验结合/阻断概率。

`V4-F/test32` 在本工作流中访问计数固定为 0。

## 严格 nested 设计

- 外层：5 个 whole-parent folds，只用于最终 open outer evaluation。
- 内层：每个 outer-train 内 5 个 whole-parent folds，只用于选择 H0/H1/H2。
- inner seed 固定为 43。
- outer refit 使用 43/97/193 三 seed ensemble。
- 每个 outer × lane 独立选择超参数；不得看 outer-test 指标后改选择。

固定 shortlist：

| ID | epoch | lr | wd | Huber beta |
|---|---:|---:|---:|---:|
| H0 | 8 | 1e-4 | 0.02 | 0.03 |
| H1 | 16 | 2e-4 | 0.02 | 0.03 |
| H2 | 16 | 1e-4 | 0.03 | 0.04 |

inner 选择顺序固定为：`Rdual Spearman` 最大、`Rdual MAE` 最小、`Rdual RMSE` 最小、最后按 H0/H1/H2 字典序打破平局。

## 冻结 DAG

- 225 个 GPU inner jobs = 5 outer × 5 inner × 3 lanes × 3 H。
- 15 个 CPU inner selection jobs = 5 outer × 3 lanes。
- 45 个 GPU outer refit jobs = 5 outer × 3 lanes × 3 seeds。
- 15 个 CPU outer ensemble/evaluation jobs。
- 1 个 CPU final open outer collector。
- 合计 301 jobs，其中 GPU 270、CPU 31。

GPU allowlist 固定为 Node1 的 `1/2/4/5`；最多同时 4 个 GPU job。CPU job 最多 2 个并发，每 job `OMP/MKL=4`。

## 自动启动门

新的等待型 watcher 只有在同时满足以下条件后才能启动：

1. V2.4 strict V1.2.1 runtime `TERMINAL.json == {returncode:0,status:PASS}`；
2. V2.5 meta evaluator `TERMINAL.json.status == PASS`；
3. GPU 1/2/4/5 均无活跃 compute PID；
4. nonlaunching package、job graph、冻结合同和 authorization overlay 哈希全部闭合。

任一 gate 不满足继续等待；任一终态为 FAIL 则 fail-closed，禁止训练。
