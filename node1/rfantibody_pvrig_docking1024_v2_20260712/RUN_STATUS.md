# 运行状态

更新时间：2026-07-13 00:28 CST

## 当前阶段

- 已完成旧流程、hotspot、scaffold、GPU/CPU 资源与训练数据合同审计。
- 已冻结 48-arm V2 设计规格：计划生成 384 backbones、1,536 raw sequences，并从中冻结 1,024 条 docking cohort；真实 cohort 尚未生成。
- 已生成 3 个 FR2 VHHified scaffold 原型；hallmark 为 1.0、5-aa hydrophobic-run 为 0，正式 `VTVSS` artifact 正等待资源门控后重冻结。
- 第一次 4-arm RFdiffusion + ProteinMPNN smoke 已通过，但它只作为补 FR4 前的诊断结果。
- 已加入 scaffold 层 `VTVSS` 修复、SHA/CDR label preflight 和第二次 smoke 的正式门槛。
- 三个后台控制器已经在 node1 运行：generation、RF2/NBB2/HADDOCK、双参考后处理/训练 ETL。
- node1 当前另一个 RFantibody 项目约有 28 个进程、`load1` 约 190-220；本流程正在资源门控中等待，不抢占现有任务。
- 等负载降到 generation 门槛 72 且 GPU pool 空闲后，控制器会自动继续，无需手工重启。

## 当前资源快照

```text
GPU pool: 1,2,3,4,5,7
CPU: 64 cores
RAM: 503 GiB
/data free: about 20 TB
```

HADDOCK3/双参考后处理将根据实时 `load1` 动态限流；基线负载约 60 时只启动约 1 个 4-core HADDOCK 作业，负载下降后再扩并发。其他项目正在使用 GPU/CPU 时，本流程等待，不主动终止对方任务。

## 已验证的代码合同

- RF2 contract tests：2 项通过。
- NBB2/HADDOCK orchestration contract tests：3 项通过。
- training dataset contract tests：3 项通过。
- Python AST、JSON 和全部 shell syntax：通过。
- 真实第一代 HADDOCK pose 经 chain `B -> T` 回归后，V2 双参考流程成功输出 8X6B `BLOCKER_LIKE_A`、9E6Y `BLOCKER_PLAUSIBLE_B` 和 consensus `SINGLE_BASELINE_BLOCKER_RECHECK`。

## 尚未完成

- 1,536 条原始生成；
- 1,024 条 exact-unique cohort 冻结；
- 1,024 条 sequence QC；
- 不少于 1,000 条 RF2；
- 不少于 1,000 条 NBB2 + HADDOCK3；
- pose-level 能量/双基线几何 ETL；
- leakage-safe split 与最终合同测试。
