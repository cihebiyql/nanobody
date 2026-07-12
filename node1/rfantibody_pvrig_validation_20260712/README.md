# PVRIG RFantibody 候选结构与阻断验证

更新时间：2026-07-12

## 是否需要运行结构预测和 Docking

需要，但必须作为**分层验证漏斗**运行，不能把 1,000 条序列全部送入 NanoBodyBuilder2 和 HADDOCK3。

RFantibody 已为候选生成了目标条件化的 VHH-PVRIG 复合物设计姿势。后续结构流程要回答四个彼此独立的问题：

1. `sequence QC`：序列是否像可表达、可开发的 VHH；这不证明结合。
2. `design-pose audit`：原始 RFantibody 姿势是否落在 PVRIG-PVRL2 界面并产生足够遮挡；这不证明姿势可恢复。
3. `RF2 pose-recovery`：不给模型暴露设计 hotspot 时，是否仍能恢复相近结合姿势；这是防止“按提示画答案”的关键独立检查。
4. `NanoBodyBuilder2 + HADDOCK3`：从独立 VHH 单体结构重新对接后，8X6B 和 9E6Y 两个 PVRIG-PVRL2 基线是否都支持 blocker-like 几何。

因此，推荐且冻结的流程是：

```text
1,000 条序列 QC
  -> 200 个 RFdiffusion backbone 的原始 pose 审计
  -> 每个优先 backbone 选择 1-2 条序列
  -> 约 52-104 个 RF2 pose-recovery 作业
  -> RF2 通过者中选 Top 30-50
  -> NanoBodyBuilder2 + HADDOCK3
  -> 8X6B/9E6Y 双基线 blocker 几何共识
```

## 为什么不直接对 1,000 条全部 Docking

- 同一 RFdiffusion backbone 上的多个 ProteinMPNN 序列高度相关，全量 docking 浪费算力并夸大样本独立性。
- 直接从 FASTA 重新 docking 会丢掉 RFantibody 原始 design pose，无法检验设计姿势能否被独立模型恢复。
- HADDOCK restraint 如果把全部 CDR 强制拉向完整 PVRIG hotspot 集合，会引入确认偏差；这类结果只能叫“约束下可形成该姿势”，不能叫独立阻断证据。
- HADDOCK score、RF2 confidence、序列 binder score 和 blocker 几何是不同证据轴，不能合成一个未经校准的“结合分数”。

## 当前已知证据

- RFantibody 原始输出：1,600 条 sequence-pose 记录、1,494 条 raw exact-unique、最终 1,000 条 exact-unique；A/B/C/D 各 250 条。
- 最终 1,000 条来自 171 个不同 backbone，单 backbone 最多 6 条，因此结构阶段应先按 backbone 去冗余。
- 预审计的 200 个 backbone 中，198 个在 8X6B 对齐后对 PVRL2 有任意遮挡；52 个同时满足：总遮挡 `>=500 A^2`、CDR3 遮挡 `>=100 A^2`、CDR3 比例 `>=0.15`。
- 但 200 个 pose 均未达到旧规则的 `hotspot_overlap >=14/23`。这是因为本轮生成只使用 3-4 个稀疏 hotspot，而旧 classifier 针对完整界面 hotspot，二者口径不同。不能用这一项直接淘汰本批，也不能事后降低阈值制造阳性。
- B 组原始 hotspot 距离明显更差，必须在 RF2 shortlist 前单独分层，不能把四组视为等价候选池。

## 科学标签边界

本目录所有结果都是计算优先级，不是实验结论：

- RFantibody 生成成功：`generated candidate`
- sequence QC 通过：`sequence-qualified candidate`
- RF2 恢复姿势：`pose-recovered candidate`
- 双基线 blocker-like：`computational blocker-priority candidate`

在没有 SPR/BLI、竞争结合或细胞阻断实验前，不得写成已验证 binder、Kd 或 blocker。

## 目录

```text
config/      冻结参数
inputs/      规范化输入及来源说明
manifests/   哈希、资源和运行清单
scripts/     本地准备、node1 启动和轮询脚本
qc/          1,000 条序列 QC
pose_audit/  RFantibody 原始复合物姿势审计
rf2/         RF2 pose-recovery
docking/     NanoBodyBuilder2/HADDOCK3 与双基线结果
reports/     中文汇总报告
tests/       输入适配和标签边界测试
logs/        本地运行日志
```

原始 RFantibody 交付目录保持只读：

```text
/mnt/d/work/抗体/node1/rfantibody_pvrig_1000
/data/qlyu/projects/pvrig_rfantibody_1000_20260712
```

