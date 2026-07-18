# Contact-gradient calibration V1 → V1.2 替代审计

- 日期：2026-07-18
- 阶段：正式 Residue V2 OOF 之前
- V4-F/test32 访问：0
- prediction metric 用于选权：否

## V1：失败并保留

V1 在 Node1 完成 target ESM2 augmentation 后，四个 lane 都在 trainer import
阶段失败：

```text
ModuleNotFoundError: No module named 'build_residue_graph_cache_v2'
```

根因是 calibration bundle 未闭合 trainer 的两个 repo-local 依赖：

```text
build_residue_graph_cache_v2.py
domain_balance_v2.py
```

V1 没有产生 lane `RESULT.json`，没有运行 selector，没有产生 amendment，
也没有启动正式 OOF。V1 launcher、matrix、bundle 和 runtime 失败证据均保留不改。

## V1.1：导入闭合通过，但因资源上限终止

V1.1 新增并绑定上述两个依赖，真实 bundle layout 的 trainer import
已通过。真实运行启动后，4 个 lane 进程各自使用约 14–16 个 CPU
核，总计接近 64 核，超过 Node1 约一半 CPU 的资源约束。

因此在任何 lane `RESULT.json`、selector 或 amendment 产生之前，已对独立
process group 发送 `SIGTERM`。V1.1 partial runtime 保留，不删除、不继续声称为同一版本。

## V1.2：当前执行版本

V1.2 只增加资源上限，训练参数、数据、四个 lane、固定网格和选择规则
与 V1.1 相同：

```text
OMP_NUM_THREADS=8
MKL_NUM_THREADS=8
OPENBLAS_NUM_THREADS=8
NUMEXPR_NUM_THREADS=8
```

4 个 lane 的约束总上限约为 32 CPU 核，GPU1–4 各运行一个 lane，GPU5
只运行已完成的固定 PVRIG target augmentation。V1.2 不修改原
`PREREGISTRATION_V2.json`，只能通过冻结 selector 产生独立 amendment。

## 版本边界

```text
V1   = FAIL_PREPRODUCTION_MISSING_LOCAL_IMPORT_CLOSURE
V1.1 = STOPPED_PREPRODUCTION_CPU_RESOURCE_CAP
V1.2 = CURRENT_OPEN_ONLY_CALIBRATION_EXECUTION
```

三个版本都不是正式 OOF 结果，不是模型性能证据。
