# 运行状态

更新时间：2026-07-12 23:50 CST

## 当前阶段

- 已完成旧流程、hotspot、scaffold、GPU/CPU 资源与训练数据合同审计。
- 已冻结 48-arm V2 生成设计：384 backbones、1,536 raw sequences、1,024 docking cohort。
- 已生成 3 个 VHHified scaffold；FR2 hallmark 为 1.0，5-aa hydrophobic-run 为 0。
- 正在 node1 运行 4-arm RFdiffusion + ProteinMPNN smoke。
- 全量生成尚未启动；必须等待 smoke 的结构、标签和候选 QC 验收通过。

## 当前资源快照

```text
GPU pool: 1,2,3,4,5,7
CPU: 64 cores
RAM: 503 GiB
/data free: about 20 TB
```

HADDOCK3 将根据实时 `load1` 动态限流。其他项目正在使用 GPU/CPU 时，本流程等待，不主动终止对方任务。

## 尚未完成

- 1,536 条原始生成；
- 1,024 条 exact-unique cohort 冻结；
- 1,024 条 sequence QC；
- 不少于 1,000 条 RF2；
- 不少于 1,000 条 NBB2 + HADDOCK3；
- pose-level 能量/双基线几何 ETL；
- leakage-safe split 与最终合同测试。

