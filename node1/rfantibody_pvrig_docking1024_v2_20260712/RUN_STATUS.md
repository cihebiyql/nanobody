# 运行状态

更新时间：2026-07-13 08:41 CST

## 当前阶段

- 已冻结 48-arm V2 设计规格：`6 hotspot patches x 4 scaffolds x 2 H3 regimes`。
- 4 个 scaffold 已经 PyRosetta 末端修复为 canonical `VTVSS`，且 PDB chain `H` 和 `H1/H2/H3` label 回归检查通过。
- 修复后的正式 smoke 已通过：`P1_orig_S`、`P1_qrg_S`、`P1_ekg_S`、`P1_qkg_L` 均产出 1 个 backbone、TRB 和 ProteinMPNN 序列。
- 2026-07-13 02:59 CST，6 个首批 arm 全部完成，共产出 48 个 backbone、48 个 TRB 和 192 条 ProteinMPNN 序列，未见 OOM 或异常。
- primary-only 过渡已成功执行：6 条旧 lane 被逐 GPU 安全停止，新 controller 已明确携带 `config/generation_arms_primary.tsv` 启动。
- 36 个 VHHified arm 已全部完成：288 个 primary backbones 和 1,152 条 primary sequence records。连同保留的 2 个 orig 诊断 arm，实际产出 304 backbones 和 1,216 sequence records。
- 完整 48-arm 矩阵仍保留作为设计溯源；实际计划生成 288 个 primary backbones 和 16 个已在运行的 original-scaffold diagnostic backbones，删去其余不会进入 1,024 条 cohort 的 80 个诊断 backbone。
- 1,152 条 primary records 中有 1,067 条全局 exact-unique；已冻结 1,024 条 exact-unique cohort，覆盖全部 36 arms 和 288 backbones。
- 序列 QC 为 `1,024/1,024` 无 hard-fail。RF2 seed42 为 `1,024/1,024` 有输出：4 个 strict pose-recovered、813 个 low-interaction-confidence、207 个 pose-not-recovered。
- NanoBodyBuilder2 为 `1,024/1,024` 成功，并全部通过序列/主链几何验证。真实 HADDOCK smoke 已成功，全量 docking 正在运行。
- RF2 seed42/43/44 均已完成 `1,024/1,024`，共 3,072 个输出。多 seed 严格门控为 4 条正式通过、28 条近通过校准样本和 992 条不完整通过；RF2 失败/低置信只记为 QC 或 missingness，不作为负结合/负阻断标签。
- 2026-07-13 08:41 CST 实测：HADDOCK 为 `90 success / 10 running / 0 failed`，全部为 attempt 1。
- 已提前对 `PVRIG_RFAb_v2_P1_ekg_L_bb000_mpn00` 运行真实 8X6B/9E6Y 双参考后处理 smoke，4 个 selected models 全部生成 consensus 记录，后处理接口通过。

## 资源策略

node1 是 64 核共享节点。早期其他 CPU/GPU 任务曾使 `load1` 达到约 270-310，原 GPU 阶段 `MAX_LOAD1=240` 会使六条 lane 在 GPU 仍有充足显存时无限等待。根据正式 smoke 的实测结果，现采用分阶段门控；2026-07-13 08:01 CST 时 `load1` 约为 73，可用内存约 420 GiB：

```text
GPU stages (RFdiffusion/RF2/NBB2): MAX_LOAD1=400
GPU pool:                            1,2,3,4,5,7
GPU memory-used gate:               12,000 MiB per GPU
GPU task nice:                      10
OMP/MKL/OpenBLAS threads:           2 per GPU task
HADDOCK main-controller MAX_LOAD1:  240
HADDOCK sidecar1 MAX_LOAD1:         160
HADDOCK sidecar2 MAX_LOAD1:         120
HADDOCK total parallel jobs:        10 (main 2 + sidecar1 6 + sidecar2 2)
HADDOCK nice:                       15
```

这个调整只放宽低优先级 GPU 阶段的 load gate。HADDOCK3 仍保留更严格的 CPU 限流。不停止、降权或重启其他项目的任务。

## 已验证的代码合同

- controller contract tests：9 项通过。
- RF2 contract tests：4 项通过。
- NBB2/HADDOCK orchestration contract tests：3 项通过。
- training dataset contract tests：3 项通过。
- Python AST、JSON 和 shell syntax：通过。
- 真实第一代 HADDOCK pose 经 chain `B -> T` 回归后，V2 双参考流程输出 8X6B `BLOCKER_LIKE_A`、9E6Y `BLOCKER_PLAUSIBLE_B` 和 consensus `SINGLE_BASELINE_BLOCKER_RECHECK`。

## 尚未完成

- 不少于 1,000 条真实 HADDOCK3 结果；
- pose-level 能量、8X6B/9E6Y 几何、失败原因和 leakage-safe split ETL；
- `reports/final_audit.json` 全部硬门槛通过。

## 声明边界

本次全量 docking 的目的是建立可训练的 pose/能量/失败数据集和候选优先级，不是把计算 docking 分数当成实验 binder、Kd 或 PVRIG-PVRL2 阻断证据。
