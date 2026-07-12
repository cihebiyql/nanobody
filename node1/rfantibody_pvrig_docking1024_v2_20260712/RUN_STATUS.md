# 运行状态

更新时间：2026-07-13 01:24 CST

## 当前阶段

- 已冻结 48-arm V2 设计规格：`6 hotspot patches x 4 scaffolds x 2 H3 regimes`。
- 4 个 scaffold 已经 PyRosetta 末端修复为 canonical `VTVSS`，且 PDB chain `H` 和 `H1/H2/H3` label 回归检查通过。
- 修复后的正式 smoke 已通过：`P1_orig_S`、`P1_qrg_S`、`P1_ekg_S`、`P1_qkg_L` 均产出 1 个 backbone、TRB 和 ProteinMPNN 序列。
- 2026-07-13 01:22 CST 已在 GPU `1,2,3,4,5,7` 启动 6 条正式 generation lane；每条 lane 顺序处理 8 个 arm。
- generation、downstream 和 postprocess 三个可恢复控制器均在 node1 后台运行。downstream 等待 `data/candidates.tsv`，postprocess 等待至少 1,000 个真实 HADDOCK 成功候选。
- 当前尚未冻结 1,024 条 cohort；因此 RF2、NanoBodyBuilder2 和 HADDOCK3 还未进入全量阶段。

## 资源策略

node1 是 64 核共享节点，当前其他 CPU/GPU 任务使 `load1` 长期约为 270-310。原 GPU 阶段 `MAX_LOAD1=240` 会使六条 lane 在 GPU 仍有充足显存时无限等待。根据正式 smoke 的实测结果，现采用分阶段门控：

```text
GPU stages (RFdiffusion/RF2/NBB2): MAX_LOAD1=400
GPU pool:                            1,2,3,4,5,7
GPU memory-used gate:               12,000 MiB per GPU
GPU task nice:                      10
OMP/MKL/OpenBLAS threads:           2 per GPU task
HADDOCK MAX_LOAD1:                  240
HADDOCK maximum parallel jobs:      2
HADDOCK nice:                       15
```

这个调整只放宽低优先级 GPU 阶段的 load gate。HADDOCK3 仍保留更严格的 CPU 限流。不停止、降权或重启其他项目的任务。

## 已验证的代码合同

- controller contract tests：6 项通过。
- RF2 contract tests：2 项通过。
- NBB2/HADDOCK orchestration contract tests：3 项通过。
- training dataset contract tests：3 项通过。
- Python AST、JSON 和 shell syntax：通过。
- 真实第一代 HADDOCK pose 经 chain `B -> T` 回归后，V2 双参考流程输出 8X6B `BLOCKER_LIKE_A`、9E6Y `BLOCKER_PLAUSIBLE_B` 和 consensus `SINGLE_BASELINE_BLOCKER_RECHECK`。

## 尚未完成

- 384 个 RFdiffusion backbones 和 1,536 条原始 ProteinMPNN 记录；
- 1,024 条 exact-unique cohort 冻结和 sequence QC；
- 不少于 1,000 条 RF2 结果；
- 不少于 1,000 条 NanoBodyBuilder2 + 真实 HADDOCK3 结果；
- pose-level 能量、8X6B/9E6Y 几何、失败原因和 leakage-safe split ETL；
- `reports/final_audit.json` 全部硬门槛通过。

## 声明边界

本次全量 docking 的目的是建立可训练的 pose/能量/失败数据集和候选优先级，不是把计算 docking 分数当成实验 binder、Kd 或 PVRIG-PVRL2 阻断证据。
