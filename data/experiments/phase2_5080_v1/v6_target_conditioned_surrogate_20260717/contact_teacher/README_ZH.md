# V6 V4-H Stage 1 residue-contact teacher（冻结实现）

## 目的

把已经冻结的 V4-H Stage 1 独立双受体 Docking 结果转换为可供 V6 使用的
**残基接触教师特征**，不改变任何 Stage 1 Docking 标签、阈值、候选状态或排序。

证据边界保持为：

```text
单 seed（917）的 8X6B/9E6Y computational Docking contact evidence
≠ binding probability
≠ affinity / Kd
≠ experimental blocking
≠ Docking Gold
```

## 冻结输入

- 本地终态包：
  `experiments/phase2_5080_v1/prepared/pvrig_v4_h_stage1_terminal_v1_20260717/`
- Node23 canonical raw root：
  `/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717`
- 固定 1,320 candidates / 2,640 jobs / seed 917 / 8X6B + 9E6Y。
- 1,281 个 `DUAL_1_SEED` 候选允许读取两个成功 job 的 Top-8 poses。
- 39 个 `TECHNICAL_INCOMPLETE` 候选保留显式 NA；即使其中某一受体 job 成功，也禁止读取其 result/pose，更不能把技术失败改成负样本。

全部 frozen counts、输入 SHA256、4.5 Å cutoff、Top-8、minimum 4 poses 均写在
`V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json`。实现会 fail closed。

## 输出

在指定的、canonical raw root 之外的新目录中一次性写出：

- `v4h_stage1_candidate_contact_teacher.tsv.gz`
- `v4h_stage1_receptor_contact_teacher.tsv.gz`
- `v4h_stage1_residue_pair_contact_teacher.tsv.gz`
- `v4h_stage1_contact_extraction_audit.json`
- `RUN_RECEIPT.json`

候选/受体表包含 39 个技术不完整候选的状态行，但所有数值字段为空。pair 表只包含
1,281 个可分析候选。所有 gzip 使用固定 `mtime=0`，行排序固定，便于内容哈希复现。

## 算法

1. 先验证本地终态包 SHA256、终态计数、canonical raw manifest/ranking/hotspot SHA256。
2. 验证 candidate→sequence→parent→job→receptor→seed 的闭包。
3. 仅对 frozen `DUAL_1_SEED` candidates 打开结果和 Top-8 HADDOCK poses。
4. 用 4.5 Å heavy-atom cutoff 提取 VHH residue–PVRIG residue pair。
5. pose 以 `1/log2(rank+1)` 归一化加权，输出 pair frequency、CDR contact mass、
   interface/hotspot coverage、8X6B/9E6Y 双通道及 dual mean/min/gap/JSD。
6. 原样带入 frozen `R_dual_min` 等候选级 Docking scalar；这些字段只是监督/审计，
   extractor 不重新计算或修改它们。

## 验证命令

```bash
PY=experiments/phase2_5080_v1/.venv-phase2-5080/bin/python
ROOT=experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/contact_teacher

$PY -m py_compile "$ROOT/src/extract_v4h_stage1_contact_teacher.py"
$PY -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v
```

真实 Node23 运行前先执行 `--dry-run`。dry-run 只验证元数据、job results 和 pose 路径存在，
不读取 PDB 坐标，也不创建输出目录。完整提取属于后续独立部署步骤，本实现阶段不启动重任务。
