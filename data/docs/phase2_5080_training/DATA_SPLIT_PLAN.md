# Phase 2 数据划分方案

Updated: 2026-07-09

## 数据来源分层

| 层 | 数据 | 本地路径 | 角色 |
| --- | --- | --- | --- |
| A | ZYMScott Paratope | `datasets/49_hf_broad_antibody/ZYMScott_Paratope/` | residue-level paratope/epitope 监督 |
| B | SAbDab2 single-domain structures | `datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz` + manifest | structure contact map 监督 |
| C | sdAb-DB affinity | `datasets/36_sdab_db/sdab_db_affinity_rows.csv` | 可选 pair-level affinity 标签 |
| D | PVRIG structures/masks | `datasets/00_structures/`, `model_data/pvrig_full_sequence_mask_v0.csv` | target-specific scoring，不进普通训练 |
| E | PVRIG known positives/mutants | `model_data/pvrig_blocker_*_v0.csv` | final calibration / leakage / external target test |
| F | MVP candidates | `reports/mvp_pvrig_top_candidates_v0.csv` | 推理和下一轮 docking，不进训练 |

## 划分原则

### 1. 不用 PVRIG 阳性训练普通模型

PVRIG known-positive/blocking VHH 太少，且是比赛查重/校准对象。因此：

```text
PVRIG positives -> calibration / leakage / external target test
PVRIG mutants  -> robustness / leakage / false-positive audit
PVRIG Top candidates -> inference only
```

不进入 train/val/test 的普通监督训练。

### 2. ZYMScott 保留原始 split

`ZYMScott_Paratope` 已有：

```text
train.csv
val.csv
test.csv
```

Phase 2A 先保留原 split，便于和 Phase 1 baseline 横向比较。后续如果发现同 PDB/同抗原泄漏，再额外生成 strict cluster split。

### 3. SAbDab2 结构数据按 group split

结构数据不能按 residue/contact 行随机切分，否则同一个复合物会泄漏到 train 和 val/test。必须以 complex/group 为单位：

```text
group_key = pdb_id + antibody_chain_ids + antigen_chain_ids
```

进一步建议使用：

```text
antigen_cluster_id + vhh_cdr3_cluster_id + pdb_id
```

划分比例：

| split | 比例 | 用途 |
| --- | ---: | --- |
| train | 70% | 训练多任务模型 |
| val | 15% | 调阈值、早停、模型选择 |
| test | 15% | 最终报告，不调参 |
| pvrig_external | 固定 | PVRIG calibration/control 专用外部测试 |

### 4. 相似性泄漏规则

进入 val/test 的样本，应避免和 train 有明显泄漏：

| 规则 | 建议阈值 | 动作 |
| --- | ---: | --- |
| VHH full identity | >= 90% | 不跨 split |
| CDR3 identity | >= 80% | 不跨 split |
| antigen identity | >= 70% | 尽量不跨 split，至少进入 same antigen cluster |
| same PDB / same complex | 任意 | 绝不跨 split |

## 输出文件

计划生成：

```text
experiments/phase2_5080_v1/data_splits/zym_paratope_split_manifest_v1.csv
experiments/phase2_5080_v1/data_splits/sabdab2_structure_group_split_v1.csv
experiments/phase2_5080_v1/data_splits/pair_binding_split_v1.csv
experiments/phase2_5080_v1/data_splits/pvrig_external_calibration_manifest_v1.csv
```

每个 split manifest 至少包含：

```text
sample_id
source_dataset
source_path
split
group_key
pdb_id
vhh_seq
cdr3_seq
antigen_seq
antigen_name
label_type
label_value
leakage_notes
```

## 验收标准

1. 每个 split 非空；
2. train/val/test 行数、正负比例写入报告；
3. PDB/group 不跨 split；
4. PVRIG known-positive 不进入 train；
5. 输出 `data_split_audit.md`，列出潜在泄漏和处理结果。
