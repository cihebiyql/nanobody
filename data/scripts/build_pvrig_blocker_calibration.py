#!/usr/bin/env python3
"""Build final PVRIG blocker calibration layer from docking success/control artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path('/mnt/d/work/抗体')
DATA_ROOT = Path('/mnt/d/work/抗体/data')
DOCK = ROOT / 'docking'
PATENT = DOCK / 'calibration/patent_success_validation'
MUTANT = DOCK / 'calibration/mutant_validation_panel'
SUCCESS = DOCK / 'success_case_validation'
OUT = DATA_ROOT / 'model_data'
REPORTS = DATA_ROOT / 'reports'


def clean(v: Any) -> str:
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except Exception:
        pass
    return str(v).strip()


def read_fasta(path: Path) -> str:
    if not path.exists():
        return ''
    parts = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('>'):
            continue
        parts.append(line)
    return ''.join(parts)


def rel(path: Any) -> str:
    text = clean(path)
    if not text:
        return ''
    p = Path(text)
    try:
        return str(p.relative_to(DATA_ROOT))
    except Exception:
        try:
            return str(p.relative_to(ROOT))
        except Exception:
            return str(p)


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_positive() -> tuple[pd.DataFrame, pd.DataFrame]:
    manifest = load_csv(PATENT / 'batch_manifest.csv')
    consensus = load_csv(PATENT / 'batch_consensus_summary.csv')
    if manifest.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = manifest.merge(
        consensus,
        on=['recommended_order', 'molecule_name', 'family', 'blocking_ic50_nm', 'kd_m', 'workdir'],
        how='left',
        suffixes=('', '_consensus'),
    )
    rows = []
    pose_frames = []
    for _, r in df.iterrows():
        workdir = Path(clean(r.get('workdir')))
        fasta_files = sorted((workdir / 'inputs').glob('*_vhh.fasta'))
        seq = read_fasta(fasta_files[0]) if fasta_files else ''
        consensus_csv = Path(clean(r.get('consensus_csv')))
        if consensus_csv.exists():
            poses = pd.read_csv(consensus_csv)
            poses.insert(0, 'calibration_name', clean(r.get('calibration_name')))
            poses.insert(1, 'molecule_name', clean(r.get('molecule_name')))
            poses.insert(2, 'family', clean(r.get('family')))
            poses.insert(3, 'cohort', 'patent_success_positive')
            poses.insert(4, 'source_consensus_csv', rel(consensus_csv))
            pose_frames.append(poses)
        rows.append({
            'calibration_id': clean(r.get('calibration_name')),
            'molecule_name': clean(r.get('molecule_name')),
            'family': clean(r.get('family')),
            'label_role': 'known_positive_pvrig_blocking_vhh',
            'model_usage': 'final_calibration_thresholding_and_leakage_exclusion_not_training_positive',
            'validation_role': clean(r.get('validation_role')),
            'sequence_type': clean(r.get('sequence_type')),
            'sequence': seq,
            'sequence_length': len(seq) if seq else clean(r.get('sequence_length')),
            'cdr1': clean(r.get('cdr1')),
            'cdr1_range': clean(r.get('cdr1_range')),
            'cdr2': clean(r.get('cdr2')),
            'cdr2_range': clean(r.get('cdr2_range')),
            'cdr3': clean(r.get('cdr3')),
            'cdr3_range': clean(r.get('cdr3_range')),
            'blocking_ic50_nm': clean(r.get('blocking_ic50_nm')),
            'kd_m': clean(r.get('kd_m')),
            'reporter_ec50_nm': clean(r.get('reporter_ec50_nm')),
            'pose_count': clean(r.get('pose_count')),
            'case_level_call': clean(r.get('case_level_call')),
            'consensus_blocker_like_a': clean(r.get('consensus_blocker_like_a')),
            'single_baseline_blocker_recheck': clean(r.get('single_baseline_blocker_recheck')),
            'blocker_plausible_b': clean(r.get('blocker_plausible_b')),
            'evidence_inference_only_e': clean(r.get('evidence_inference_only_e')),
            'top_model': clean(r.get('top_model')),
            'top_model_consensus_class': clean(r.get('top_model_consensus_class')),
            'top_model_baseline_classes': clean(r.get('top_model_baseline_classes')),
            'top_8x6b_class': clean(r.get('top_8x6b_class')),
            'top_8x6b_hotspot': clean(r.get('top_8x6b_hotspot')),
            'top_8x6b_total_occlusion': clean(r.get('top_8x6b_total_occlusion')),
            'top_8x6b_cdr3_occlusion': clean(r.get('top_8x6b_cdr3_occlusion')),
            'top_8x6b_cdr3_fraction': clean(r.get('top_8x6b_cdr3_fraction')),
            'top_9e6y_class': clean(r.get('top_9e6y_class')),
            'top_9e6y_hotspot': clean(r.get('top_9e6y_hotspot')),
            'top_9e6y_total_occlusion': clean(r.get('top_9e6y_total_occlusion')),
            'top_9e6y_cdr3_occlusion': clean(r.get('top_9e6y_cdr3_occlusion')),
            'top_9e6y_cdr3_fraction': clean(r.get('top_9e6y_cdr3_fraction')),
            'workdir': rel(workdir),
            'input_fasta': rel(fasta_files[0]) if fasta_files else '',
            'consensus_csv': rel(consensus_csv),
            'usage_boundary': clean(r.get('usage_boundary')),
        })
    pos = pd.DataFrame(rows)
    pose = pd.concat(pose_frames, ignore_index=True) if pose_frames else pd.DataFrame()
    return pos, pose


def build_mutant() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = load_csv(MUTANT / 'mutant_panel.csv')
    status = load_csv(MUTANT / 'mutant_panel_status.csv')
    leakage = load_csv(MUTANT / 'mutant_panel_sequence_leakage.csv')
    if panel.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = panel.merge(status, on=['panel_order', 'mutant_name', 'base_molecule', 'mutation_class', 'mutations_1based', 'workdir'], how='left')
    if not leakage.empty:
        df = df.merge(leakage, left_on='mutant_name', right_on='candidate_id', how='left')
    rows = []
    pose_frames = []
    for _, r in df.iterrows():
        consensus_csv = Path(clean(r.get('workdir'))) / 'reports' / f"{clean(r.get('mutant_name'))}_8x6b_9e6y_consensus.csv"
        if not consensus_csv.exists():
            # Some rows only expose consensus_csv as yes/no in status; infer from workdir pattern.
            consensus_csv = Path(clean(r.get('workdir'))) / 'reports' / 'consensus.csv'
        if consensus_csv.exists():
            poses = pd.read_csv(consensus_csv)
            poses.insert(0, 'mutant_name', clean(r.get('mutant_name')))
            poses.insert(1, 'base_molecule', clean(r.get('base_molecule')))
            poses.insert(2, 'family', clean(r.get('family')))
            poses.insert(3, 'cohort', 'mutant_control_panel')
            poses.insert(4, 'source_consensus_csv', rel(consensus_csv))
            pose_frames.append(poses)
        rows.append({
            'control_id': clean(r.get('mutant_name')),
            'base_molecule': clean(r.get('base_molecule')),
            'family': clean(r.get('family')),
            'control_type': clean(r.get('control_type')),
            'mutation_class': clean(r.get('mutation_class')),
            'mutations_1based': clean(r.get('mutations_1based')),
            'changed_cdr': clean(r.get('changed_cdr')),
            'intended_role': clean(r.get('intended_role')),
            'label_role': 'mutant_or_leakage_control_not_new_design',
            'model_usage': 'calibration_robustness_leakage_and_false_positive_control',
            'sequence': clean(r.get('sequence')),
            'sequence_length': clean(r.get('sequence_length')),
            'cdr1_range': clean(r.get('cdr1_range')),
            'cdr2_range': clean(r.get('cdr2_range')),
            'cdr3_range': clean(r.get('cdr3_range')),
            'structure_qc_sane': clean(r.get('structure_qc_sane')),
            'consensus_rows': clean(r.get('consensus_rows')),
            'consensus_blocker_like_a': clean(r.get('consensus_blocker_like_a')),
            'single_baseline_blocker_recheck': clean(r.get('single_baseline_blocker_recheck')),
            'blocker_plausible_b': clean(r.get('blocker_plausible_b')),
            'evidence_inference_only_e': clean(r.get('evidence_inference_only_e')),
            'nearest_reference_id': clean(r.get('nearest_reference_id')),
            'identity_fraction': clean(r.get('identity_fraction')),
            'same_length_hamming_distance': clean(r.get('same_length_hamming_distance')),
            'leakage_label': clean(r.get('leakage_label')),
            'recommended_action': clean(r.get('recommended_action')),
            'workdir': rel(clean(r.get('workdir'))),
        })
    mut = pd.DataFrame(rows)
    pose = pd.concat(pose_frames, ignore_index=True) if pose_frames else pd.DataFrame()
    return mut, pose


def build_thresholds() -> pd.DataFrame:
    frames = []
    for cohort, path in [
        ('patent_success_positive', PATENT / 'threshold_sensitivity_summary.csv'),
        ('mutant_control_panel', MUTANT / 'mutant_panel_threshold_sensitivity_summary.csv'),
    ]:
        df = load_csv(path)
        if not df.empty:
            df.insert(0, 'cohort', cohort)
            df.insert(1, 'source_file', rel(path))
            frames.append(df)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def build_file_manifest() -> pd.DataFrame:
    files = [
        ('positive_case_manifest', PATENT / 'batch_manifest.csv', '11 known positive/blocking VHH/HCVR calibration cases with CDR and assay labels'),
        ('positive_case_status', PATENT / 'batch_status.csv', 'structure/docking/consensus artifact completion flags'),
        ('positive_case_consensus', PATENT / 'batch_consensus_summary.csv', 'case-level blocker-like consensus summaries'),
        ('positive_case_cdr_ranges', PATENT / 'patent_success_validation_cdr_ranges.csv', 'locked CDR ranges and sequence-numbering evidence'),
        ('positive_threshold_sensitivity', PATENT / 'threshold_sensitivity_summary.csv', '81 threshold settings for positive cohort'),
        ('mutant_panel_manifest', MUTANT / 'mutant_panel.csv', '36 mutant/control sequences and intended control roles'),
        ('mutant_panel_status', MUTANT / 'mutant_panel_status.csv', 'mutant structure/docking/consensus status and counts'),
        ('mutant_leakage', MUTANT / 'mutant_panel_sequence_leakage.csv', 'exact/near known-positive leakage labels'),
        ('mutant_stratification', MUTANT / 'mutant_panel_result_stratification_summary.csv', 'control stratification summary'),
        ('mutant_threshold_sensitivity', MUTANT / 'mutant_panel_threshold_sensitivity_summary.csv', '81 threshold settings for mutant/control cohort'),
        ('judgment_rules', SUCCESS / 'blocker_judgment_rules_v2.json', 'blocker-like geometry rules used by workflow'),
        ('judgment_standards', SUCCESS / 'blocker_design_judgment_standards_v2.md', 'human-readable standards and boundaries'),
        ('completion_audit', SUCCESS / 'WORKFLOW_COMPLETION_AUDIT.md', 'locked completion audit and final verification command set'),
        ('mechanism_criteria', SUCCESS / 'success_case_mechanism_criteria_matrix.csv', 'mechanistic criteria: binder vs blocker, Kd vs IC50, soft hotspots'),
        ('known_positive_fasta', ROOT / 'positives/known_positive_antibodies.fasta', 'known-positive sequence references for leakage exclusion'),
        ('known_positive_cdr_table', ROOT / 'positives/known_positive_CDR_table.csv', 'known-positive CDR references for similarity exclusion'),
        ('positive_cdr_similarity_exclusion', ROOT / 'positives/positive_CDR_similarity_exclusion_table.csv', 'CDR similarity exclusion table for known positives'),
    ]
    rows = []
    for role, path, desc in files:
        rows.append({'artifact_role': role, 'path': rel(path), 'exists': path.exists(), 'description': desc})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    positive, positive_pose = build_positive()
    mutant, mutant_pose = build_mutant()
    thresholds = build_thresholds()
    manifest = build_file_manifest()

    positive.to_csv(OUT / 'pvrig_blocker_positive_calibration_v0.csv', index=False)
    positive_pose.to_csv(OUT / 'pvrig_blocker_positive_pose_labels_v0.csv', index=False)
    mutant.to_csv(OUT / 'pvrig_blocker_mutant_control_calibration_v0.csv', index=False)
    mutant_pose.to_csv(OUT / 'pvrig_blocker_mutant_pose_labels_v0.csv', index=False)
    thresholds.to_csv(OUT / 'pvrig_blocker_threshold_sensitivity_v0.csv', index=False)
    manifest.to_csv(OUT / 'pvrig_blocker_calibration_file_manifest_v0.csv', index=False)

    summary = {
        'positive_cases': int(len(positive)),
        'positive_pose_rows': int(len(positive_pose)),
        'positive_families': positive['family'].astype(str).value_counts().to_dict() if not positive.empty else {},
        'mutant_controls': int(len(mutant)),
        'mutant_pose_rows': int(len(mutant_pose)),
        'mutant_leakage_counts': mutant['leakage_label'].astype(str).value_counts().to_dict() if not mutant.empty else {},
        'threshold_rows': int(len(thresholds)),
        'threshold_cohorts': thresholds['cohort'].astype(str).value_counts().to_dict() if not thresholds.empty else {},
        'rules_manifest_rows': int(len(manifest)),
        'model_integration_rule': 'Use these artifacts for final calibration/gating/leakage exclusion, not as ordinary de novo training positives.',
    }
    (OUT / 'pvrig_blocker_calibration_summary_v0.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')

    report = f"""# PVRIG blocker 最终校准层 v0

生成时间：2026-07-08  
输入来源：`/mnt/d/work/抗体/docking`  
输出目录：`model_data/`

## 结论

这批 WO2021180205A1 阳性 VHH/HCVR 和 mutant/control panel **应该接在模型最后校对层**，而不是混进普通训练集。

原因：

- 它们包含已知阳性/阻断案例，直接训练会造成泄漏。
- 它们有结构预测、HADDOCK3 docking、8X6B/9E6Y 双基线和 consensus，更适合校准 blocker-like 几何阈值。
- mutant/control panel 里 exact/near known-positive 很多，适合做 false-positive/鲁棒性/泄漏门控，而不是新候选正例。

## 生成的校准文件

| 文件 | 行数 | 用途 |
| --- | ---: | --- |
| `model_data/pvrig_blocker_positive_calibration_v0.csv` | {len(positive)} | 11 条已知阳性/阻断 VHH/HCVR，含 CDR、序列、IC50/Kd、case-level consensus |
| `model_data/pvrig_blocker_positive_pose_labels_v0.csv` | {len(positive_pose)} | 阳性案例逐 pose consensus label，用于校准 docking/blocker 几何阈值 |
| `model_data/pvrig_blocker_mutant_control_calibration_v0.csv` | {len(mutant)} | 36 条 mutant/control panel，含泄漏标签、突变类别和 consensus 统计 |
| `model_data/pvrig_blocker_mutant_pose_labels_v0.csv` | {len(mutant_pose)} | mutant/control 逐 pose label，用于鲁棒性与 false-positive 检查 |
| `model_data/pvrig_blocker_threshold_sensitivity_v0.csv` | {len(thresholds)} | positive + mutant 两套 81 阈值网格，共 {len(thresholds)} 行 |
| `model_data/pvrig_blocker_calibration_file_manifest_v0.csv` | {len(manifest)} | 校准层引用的源文件清单 |
| `model_data/pvrig_blocker_calibration_summary_v0.json` | 1 | 聚合统计和集成规则 |

## 已锁定的聚合统计

- positive cases: {len(positive)}
- positive pose rows: {len(positive_pose)}
- positive families: {json.dumps(summary['positive_families'], ensure_ascii=False)}
- mutant/control records: {len(mutant)}
- mutant/control pose rows: {len(mutant_pose)}
- mutant leakage labels: {json.dumps(summary['mutant_leakage_counts'], ensure_ascii=False)}
- threshold sensitivity rows: {len(thresholds)}

## 接入模型的方式

最终候选评分应该分两层：

```text
第一层：AI model prior
  - paratope probability
  - epitope probability
  - VHH-only/ranking score
  - PVRIG target epitope overlap

第二层：PVRIG blocker calibration gate
  - exact/near known-positive leakage exclusion
  - 8X6B + 9E6Y dual-baseline docking consensus
  - positive success threshold calibration
  - mutant/control false-positive audit
  - CDR3 disruptive/alanine retained-A manual review
```

推荐最终候选表新增列：

```text
ai_binding_rank_score
ai_paratope_confidence
ai_pvrig_epitope_overlap_top20
ai_pvrig_epitope_overlap_top50
known_positive_identity_fraction
leakage_label
haddock_8x6b_class
haddock_9e6y_class
dual_baseline_consensus_class
positive_threshold_supported
mutant_panel_false_positive_risk
manual_pose_review_required
final_blocker_like_calibrated_label
```

## 使用边界

- `pvrig_blocker_positive_calibration_v0.csv`：只能作为 positive calibration / threshold / leakage reference，不能当新设计候选。
- `pvrig_blocker_mutant_control_calibration_v0.csv`：只能作为 perturbation/control/leakage/false-positive audit，不能当新设计候选。
- 新候选如果 exact/near known-positive，必须从新候选排序中剔除，除非明确标为 control。
- 最终声明必须是 computational blocker-like geometry，不是实验 Kd/IC50 证明。
"""
    (REPORTS / 'pvrig_blocker_final_calibration_layer_v0.md').write_text(report, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
