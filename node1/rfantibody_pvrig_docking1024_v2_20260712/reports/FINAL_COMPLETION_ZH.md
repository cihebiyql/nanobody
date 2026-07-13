# RFantibody-PVRIG 1,024 条全量结构与 Docking 数据工程完成报告

更新时间：2026-07-13 21:20 CST

## 1. 最终结论

本轮已对同一批 1,024 条 exact-unique VHH 完成全量 RF2、NanoBodyBuilder2、HADDOCK3、8X6B/9E6Y 双参考后处理和训练数据 ETL。

| 阶段 | 最终结果 |
|---|---:|
| 冻结候选 | 1,024 条 candidate_id |
| exact-unique 序列 | 1,024 |
| sequence QC | 1,024/1,024，hard-fail = 0 |
| RF2 seed42 | 1,024/1,024 |
| RF2 seed43 | 1,024/1,024 |
| RF2 seed44 | 1,024/1,024 |
| NanoBodyBuilder2 | 1,024/1,024 success |
| HADDOCK3 | 1,024/1,024 success |
| 8X6B/9E6Y 双参考后处理 | 1,024/1,024 success |
| baseline metric rows | 8,192 |
| pose-consensus rows | 4,096 |
| selected-pose 训练特征 | 8,606 |
| final audit | PASS |
| independent validation | PASS（25/25 checks） |

权威结果文件：

```text
reports/final_audit.json
reports/independent_final_validation.json
data/training_dataset/dataset_manifest.json
```

## 2. 远程与本地路径

node1 完整运行根目录：

```text
/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712
```

本地轻量交付镜像：

```text
/mnt/d/work/抗体/node1/rfantibody_pvrig_docking1024_v2_20260712
```

本地已镜像核心 TSV、final training dataset、报告、状态标记和可复现脚本，约 25 MB。大体积原始资产（RFdiffusion/RF2/NBB2/HADDOCK PDB、TRB 和失败尝试目录）保留在 node1。本地镜像范围和每个文件的 SHA256 见：

```text
reports/local_mirror_manifest.json
```

## 3. 生成与冻结数据

设计空间保留完整的：

```text
6 hotspot patches x 4 scaffolds x 2 H3 regimes = 48 arms
```

正式 cohort 只从 36 个 VHHified primary arms 选择：

```text
36 arms x 8 RFdiffusion backbones x 4 ProteinMPNN sequences
= 1,152 primary records
```

原始 1,152 条记录中有 1,067 条全局 exact-unique 序列。冻结器使用自适应平衡 max-flow，最终选出 1,024 条，覆盖全部 36 arms 和 288 个 primary backbones，且无已知阳性 exact match。

核心来源：

```text
data/candidates.tsv
data/generation_freeze_summary.json
inputs/leakage_reference.fasta
```

## 4. RF2 结果如何解读

3 个 seed 共产出 3,072 条 RF2 记录，无缺失。多 seed 门控结果：

```text
FORMAL_MULTI_SEED_PASS_2OF3_WITH_STRICT_SUPPORT = 4
RF2_NEAR_PASS_CALIBRATION_ONLY                 = 28
FORMAL_MULTI_SEED_FAIL_COMPLETE               = 992
```

这些结果表示 RF2 blind-pose recovery 和 interaction-confidence QC，不表示实验不结合。`rf2_failure_label_policy` 对 3,072 行均为 `qc_status_only`，因此不得把 RF2 fail/low-confidence 当作负 binder 或负 blocker 标签。

核心文件：

```text
data/rf2_metrics.tsv
data/rf2_candidate_gates.tsv
rf2/results/rf2_multiseed_parse_summary.json
```

## 5. NanoBodyBuilder2 和 HADDOCK3

NanoBodyBuilder2 的 1,024 个单体全部通过：

- VHH 序列一致性；
- chain A 归一化；
- 主链几何；
- adjacent CA distance gate。

HADDOCK3 对 1,024 个不同 candidate_id 均完成真实 docking，不是 dry-run。每个候选保留 4-10 个 `6_seletopclusts` selected models。

共有 3 条候选在默认 `[flexref] tolerance=10` 时可重复地产出 8/10 个模型，20% 缺失率超过默认门槛。对这 3 条使用独立 rescue config：

```text
flexref tolerance = 30
emref tolerance   = 30
```

所有原失败目录均保留在 `docking/failed_haddock_attempts/`，rescue JSON 保存原/新配置哈希、原因、尝试次数和输出数。三条 rescue 最终均成功，各产出 8 个 selected models。

## 6. 8X6B/9E6Y 双参考几何

每个 candidate 对 HADDOCK 排名前 4 个 pose 做后处理：

1. 用 8X6B 计算 PVRIG-PVRL2 界面热点重叠和 CDR3 遮挡；
2. 把同一个 8X6B-guided pose 对齐到 9E6Y 做 reference-overlay scoring；
3. 保存两个 baseline 的分类和 consensus。

最终共有：

```text
1,024 successful candidates
8,192 baseline rows = 1,024 x 4 poses x 2 references
4,096 consensus rows = 1,024 x 4 poses
```

注意：9E6Y 是 overlay score，不是独立的第二次 docking。这些分数是 blocker-geometry proxy，不是阻断实验结果。

## 7. Final training dataset

主目录：

```text
data/training_dataset/
```

主要文件：

| 文件 | 行数 | 用途 |
|---|---:|---|
| `candidates.tsv` | 1,024 | 冻结序列、arm、backbone、near-CDR3 family |
| `rf2_metrics.tsv` | 3,072 | 3-seed RF2 QC/recovery |
| `monomer_qc.tsv` | 1,024 | NBB2 单体质量 |
| `docking_runs.tsv` | 1,024 | candidate-level docking 状态和代表 pose |
| `docking_pose_features.tsv` | 8,606 | selected-pose HADDOCK energy/REMARK 特征 |
| `candidate_summary.tsv` | 1,024 | 分轴 candidate-level 汇总 |
| `splits_by_backbone.tsv` | 425 | 防泄漏 split 组 |
| `failures.tsv` | 0 | final 缺失/失败记录 |

### 证据轴必须分开

`candidate_summary.tsv` 不把多种信号压成未校准总分：

- `binder` 轴：本数据无实验 binder label；1,024 条均为 `binder_axis_status=deferred`、`binder_label=unknown`；
- `pose_quality` 轴：HADDOCK score 及 pose 特征；
- `affinity_proxy` 轴：只能作为代理量，不是 Kd；
- `blocker_geometry` 轴：PVRIG-PVRL2 界面遮挡几何；
- `rf2_recovery` 轴：blind recovery/QC。

因此，这批数据适合训练 pose-quality、energy proxy、interface geometry、missingness/QC 或多任务辅助头；不应直接把 1,024 条当成实验 binder 正例。

## 8. Split 和剩余限制

硬防泄漏 key 为：

```text
backbone_group_id
arm_id
global near-CDR3 family (SequenceMatcher >= 0.80)
```

当前 1,024 条形成两个连通分量：522 和 502。为了不拆分硬分量，final split 为：

```text
train      = 522
validation = 502
test       = unavailable
```

manifest 明确标记 `model_split_feasibility=two_way_only` 和 `test_split_available=false`。如果后续必须要独立 test set，应增加与当前全局 near-CDR3 图断开的新候选家族，而不是为了凑三分而拆分现有硬分量。

## 9. 可复现验收

在 node1 上运行独立验收：

```bash
/data/qlyu/anaconda3/envs/boltz/bin/python \
  scripts/validate_final_delivery.py \
  --run-root /data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712
```

预期输出：

```text
status = PASS
25/25 checks = true
```

回归测试：

```bash
python3 tests/test_controller_contract.py
python3 tests/test_rf2_multiseed_contract.py
python3 tests/test_docking_orchestration_contract.py
python3 tests/test_training_dataset_contract.py
python3 -m py_compile scripts/*.py tests/*.py
bash -n scripts/*.sh
```

本轮实测通过：

```text
9 controller contract tests
4 RF2 contract tests
6 docking orchestration contract tests
6 training-dataset contract tests
```

## 10. 科学声明

本交付建立的是计算 QC、结构 pose、能量代理和界面遮挡数据集。它不提供实验 binding、Kd 或 PVRIG-PVRL2 blockade 证明。最终 binder 和 blocker 结论仍需要实验校准与验证。
