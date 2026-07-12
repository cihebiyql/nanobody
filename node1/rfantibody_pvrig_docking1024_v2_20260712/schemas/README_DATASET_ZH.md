# PVRIG RFantibody 训练数据集契约

本目录定义最终训练数据 ETL 的最小契约。构建脚本为 `scripts/build_training_dataset.py`，默认从 `data/` 读取候选与各评估结果，并写入 `data/training_dataset/`。

## 输入

- `data/candidates.tsv`：候选主表，至少需要可识别的 `candidate_id`；推荐包含 `sequence`、`arm_id`、`backbone_group_id`、`sequence_group_id`。
- `data/rf2_metrics.tsv`：RF2 recovery 轴，例如 `rf2_recovery_rmsd`、`rf2_plddt`。
- `data/monomer_qc.tsv` 或 `data/nbb2_qc.tsv`：NBB2/单体 QC 轴，例如 `monomer_qc_score`、`monomer_clash_score`。
- `data/haddock_runs/` 和/或 `data/docking_runs.tsv`：HADDOCK 运行与 selected/raw model。脚本会扫描 PDB `REMARK` 解析 score/energies。
- `data/baseline_postprocess.tsv` 或 `data/dual_baseline_postprocess.tsv`：双基线后处理，包含 affinity proxy 与 blocker geometry proxy。
- `inputs/leakage_reference.fasta`：known positives / blocking VHH 泄漏控制参考。

## 输出

脚本每次至少写出以下文件：

- `candidates.tsv`：规范化候选表，保留 known-positive 标记和序列/骨架分组键。
- `rf2_metrics.tsv`：按候选补齐后的 RF2 recovery 轴，缺失写 `status=missing`。
- `monomer_qc.tsv`：按候选补齐后的 NBB2/单体 QC 轴。
- `docking_runs.tsv`：按候选补齐后的 HADDOCK run 状态。
- `docking_pose_features.tsv`：从 HADDOCK raw PDB `REMARK` 解析出的 pose score/energy 特征。
- `candidate_summary.tsv`：每个候选一行的训练汇总，但 binder、pose quality、affinity proxy、blocker geometry、RF2 recovery 仍分轴保存。
- `splits_by_backbone.tsv`：按 `backbone_group_id + arm_id + sequence_group_id` 分组后的 split，避免同骨架/同 arm/近序列家族泄漏。
- `failures.tsv`：所有 missing/deferred/error，不丢失败候选。
- `dataset_manifest.json`：输入输出 sha256、计数、split 计数、missingness 计数和 final gate。

## 关键边界

- `binder_label` 只能来自实验或明确 curated calibration 信息；不能由 HADDOCK score、affinity proxy、blocker geometry 或 RF2 recovery 推断。
- `pose_quality_haddock_score` 是 docking pose quality 轴；不是 binder 标签。
- `affinity_proxy_score` 是双基线 affinity proxy 轴；不是 blocker geometry，也不是实验亲和力。
- `blocker_geometry_score` 是面向 PVRIG-PVRL2 界面/热点的阻断几何轴；不等同于普通 binder。
- `rf2_recovery_rmsd`、`rf2_plddt` 是 RF2 recovery/结构一致性轴；不等同于 docking 或 blocker。
- known positives 只能进入 `calibration_holdout`，不能作为普通训练正例。

## partial 与 final

- `--mode partial`：真实 RF2/QC/HADDOCK/双基线结果尚未齐全时使用。候选不会被丢弃，缺失原因写入 `failures.tsv`，汇总列使用 `missing`/`deferred`。
- `--mode final`：正式训练冻结时使用。要求 `completed_docking_candidates >= 1000`，不允许 known positives 泄漏到 train，并要求 docking 结果完成；否则脚本非零退出。

## 示例

```bash
python scripts/build_training_dataset.py --mode partial
python scripts/build_training_dataset.py --mode final --output-dir data/training_dataset_final
```
