# PVRIG RFantibody V2：1,024 条候选的 RF2 与 Docking 数据工程

## 目标

概念和溯源说明（P2/P3/P4、8X6B/9E6Y、阳性 VHH 使用范围与当前校准标准）见：

```text
reports/PIPELINE_ORIGIN_CALIBRATION_GOLD_STANDARD_ZH.md
```

本目录是第一代 RFantibody 结果的独立 V2 运行包，不修改第一代交付。最终停止条件是：

1. 冻结不少于 1,024 条 exact-unique VHH 序列；
2. 同一批候选至少 1,000 条完成 RF2；
3. 同一批候选至少 1,000 条完成 NanoBodyBuilder2 单体建模和一次真实 HADDOCK3 docking；
4. 保存 candidate、RF2、monomer、docking run、pose、双基线几何、失败和 split 数据；
5. 通过按 RFdiffusion backbone、generation arm 和近邻序列家族分组的防泄漏验收。

这里的“完成 docking”指不同 `candidate_id` 实际完成 HADDOCK3，而不是把同一候选的多个 pose 当作多条序列。

## 为什么调整第一代策略

第一代使用 4 个稀疏 hotspot set、单一 `h-NbBCII10` scaffold 和 200 个 RFdiffusion backbone。最终 1,000 条序列只覆盖 171 个 backbone；78 条 RF2 严格 pose recovery 为 0，8X6B 与 9E6Y 的 blocker-like 几何差异也很大。

V2 不把“序列数量”当成“独立结构证据”，主要变化如下：

- 6 个 5-7 位空间 patch，覆盖 core、N-C bridge、charge/aromatic、C-terminal、upper-interface 和 holdout-ablation；
- 原始 scaffold 只作为诊断对照，正式 docking cohort 从 3 个 VHHified scaffold 中选择；
- VHHified scaffold 修复 Kabat H44/H45/H47 hallmark，并以 H50S 打断 FR2 疏水连续片段；
- 分开 H3 `5-10` 和 `11-15` 两个长度档；
- 48 个 generation arms，共 384 个 RFdiffusion backbone、1,536 条原始 MPNN 记录；
- 从 1,152 条 VHHified 原始记录中按 arm 和 backbone 均衡冻结 1,024 条。

## 冻结的生成矩阵

矩阵由 `scripts/create_generation_arms.py` 生成，唯一真值是 `config/generation_arms.tsv`：

```text
6 patches x 4 scaffolds x 2 H3 regimes = 48 arms
48 arms x 8 backbones = 384 backbones
384 backbones x 4 MPNN sequences = 1,536 raw records
3 VHHified scaffolds = 1,152 primary raw records
freeze target = 1,024 exact-unique candidates
```

GPU 运行池固定为 `1,2,3,4,5,7`。每张 GPU 顺序处理 8 个 arm，避免同一 GPU 同时启动多个 RFdiffusion/RF2 进程。

### 正式运行的 primary-only 剪枝

48-arm 表仍作为完整设计空间和溯源真值，但 `orig` 的 12 个 arm 不进入最终 docking cohort。在正式 smoke 和首批实跑已经提供 `P1_orig_S/L` 诊断对照后，后续生成切换到 `config/generation_arms_primary.tsv`：

```text
36 primary VHHified arms x 8 backbones x 4 sequences = 1,152 cohort-source records
2 completed original-scaffold diagnostic arms x 8 x 4 = 64 diagnostic records
actual planned RFdiffusion backbones = 288 primary + 16 diagnostic = 304
removed unused diagnostic work = 80 backbones + 320 sequence records
```

这个剪枝不降低 1,024 条 cohort 的原始容量：冻结算法原本就只从 36 个 `primary_vhhified` arm 的 1,152 条记录中选择。`GENERATION_ARM_TABLE` 同时约束 generation 和 collector，避免运行表与冻结表不一致。

## Scaffold 修复

PyRosetta 使用 PDB 编号突变；PDB 与 Kabat 的映射是：

| PDB 位点 | Kabat 位点 | 作用 |
|---|---|---|
| H47 | H44 | `G -> Q/E`，VHH hydrophilic hallmark |
| H48 | H45 | `L -> R/K`，VHH hydrophilic hallmark |
| H50 | H47 | `A -> G`，VHH hallmark |
| H53 | H50 | `A -> S`，打断残余 `VAAIA` 疏水连续片段 |

3 个正式 scaffold 是 `qrg`、`ekg`、`qkg`；原始 `orig` 只保留为生成对照，不进入正式 1,024 条 cohort。scaffold 的序列、突变和 SHA256 记录在 `inputs/scaffolds/scaffold_manifest.json`。

## 阶段与证据边界

以下证据必须分轴保存，不能压成一个未经校准的总分：

1. sequence QC：合成、编号、VHH hallmark、liability 和可开发性风险；
2. RFdiffusion/ProteinMPNN：生成姿势和序列兼容性，不是结合证据；
3. RF2：blind pose recovery 和 interaction confidence，不是实验 affinity；
4. NanoBodyBuilder2：VHH 单体结构可建模性；
5. HADDOCK3：受约束 docking pose 与能量代理；
6. 8X6B/9E6Y：PVRIG-PVRL2 界面遮挡几何；
7. 实验 binding、Kd 和 blockade：本计算包不提供这些实验标签。

`FINAL_POSITIVE_HIGH` 不能由 RF2 diagnostic fallback 或 full-interface-guided docking 单独产生。

## 主要入口

node1 远端根目录：

```text
/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712
```

生成 scaffold 和 arm 表：

```bash
/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python scripts/make_scaffold_variants.py \
  --source inputs/scaffolds/h-NbBCII10_source.pdb \
  --output-dir inputs/scaffolds \
  --manifest inputs/scaffolds/scaffold_manifest.json

python3 scripts/create_generation_arms.py \
  --out config/generation_arms.tsv \
  --summary config/generation_design_summary.json
```

先 smoke、再全量：

```bash
bash scripts/run_generation_smoke.sh
nohup bash scripts/launch_generation_multi_gpu.sh > logs/generation_controller.log 2>&1 &
python3 scripts/status_generation.py
```

冻结 cohort：

```bash
/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python \
  scripts/collect_and_freeze_candidates.py --target 1024
```

后续 RF2、NBB2、HADDOCK 和 dataset ETL 入口由同目录脚本提供，所有长任务都必须可恢复；不得通过删除失败目录来“提高成功率”。

推荐使用三个可恢复控制器，而不是手工逐阶段启动：

```bash
nohup env MAX_LOAD1=400 GPU_MEMORY_GATE_MB=12000 \
  bash scripts/run_generation_controller.sh \
  > logs/generation_pipeline_controller.log 2>&1 &

nohup env MAX_LOAD1=400 HADDOCK_MAX_LOAD1=240 \
  GPU_MEMORY_GATE_MB=12000 HADDOCK_MAX_PARALLEL=2 \
  bash scripts/run_downstream_controller.sh \
  > logs/downstream_pipeline_controller.log 2>&1 &

nohup env MAX_LOAD1=240 POSTPROCESS_MAX_PARALLEL=2 \
  bash scripts/run_postprocess_controller.sh \
  > logs/postprocess_pipeline_controller.log 2>&1 &
```

三个控制器通过完成标记串联：第二个等待冻结的 1,024 条 cohort，第三个等待至少 1,000 条真实 HADDOCK 成功。RF2 seed42 优先完成；seed43/44 在 NBB2 后作为 enrichment。HADDOCK 与双参考后处理都根据 `load1` 动态分配并发。

### HADDOCK 失败和 rescue

可恢复不等于删除失败证据。当一次 HADDOCK 只产出部分中间结果时，重试器先将旧 `run_dir` 移入：

```text
docking/failed_haddock_attempts/<candidate_id>/failed_before_attempt_<N>_<UTC>/
```

随后才开始一次干净重跑。如果必须放宽 HADDOCK 的 module tolerance，要使用独立 rescue config 和 JSON 报告记录原因、原/新配置哈希、尝试次数和 selected model 数；这类 rescue pose 仍然只是几何证据。

## 训练数据最低文件集

最终 `data/training_dataset/` 至少包含：

```text
candidates.tsv
rf2_metrics.tsv
monomer_qc.tsv
docking_runs.tsv
docking_pose_features.tsv
candidate_summary.tsv
splits_by_backbone.tsv
failures.tsv
dataset_manifest.json
```

HADDOCK score 及 vdW、electrostatics、desolvation、AIR/restraint violation、BSA 等字段应从机器可读表或 raw PDB `REMARK` 恢复。缺失必须有 `missing_reason`，不能用空值静默丢弃。

split 以 RFdiffusion backbone、generation arm 和全局 near-CDR3 family（`SequenceMatcher >= 0.80`）为硬防泄漏 key，先取连通分量，再对整个分量做确定性分配。如果硬分量少于 3，manifest 必须显式标记只能两路或单路 split，不得为了凑 train/validation/test 而拆分硬分量。当前 1,024 条 cohort 为两个分量（522/502），因此产出 train/validation，并标记 `test_split_available=false`。

## 资源礼让

- RFdiffusion、RF2、NanoBodyBuilder2 使用 GPU 1、2、3、4、5、7；GPU 已用显存达到 12,000 MiB 时按 lane 等待。
- GPU 阶段在当前共享节点使用 `MAX_LOAD1=400`、`nice=10` 和每任务 2 个 BLAS/OpenMP 线程；这个较高 load 门槛不用于 HADDOCK。
- HADDOCK3 由中央 load-aware 控制器调度；node1 为 64 核，当前有其他训练负载时不固定启动大量并发任务。
- 本次全量运行的实际峰值为 10 路低优先级 HADDOCK：main controller 2 + sidecar1 6 + sidecar2 2；不再继续提高并发。
- `scripts/watch_haddock_sidecars.sh` 只管理本项目的两个 sidecar。如果 scheduler 退出，它会先等孤儿 HADDOCK 任务降到已存活 scheduler 的容量内，再补齐 sidecar，避免因立即重启而瞬间超配。
- 不停止、重启或降低其他用户/项目的进程优先级。
