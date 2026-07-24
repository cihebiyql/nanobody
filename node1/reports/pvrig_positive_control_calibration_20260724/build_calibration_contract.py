#!/usr/bin/env python3
"""Build the PVRIG positive/control calibration contract from frozen artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path


OUT = Path(__file__).resolve().parent
POSITIVE_SERIES = Path(
    "/mnt/d/work/抗体/机制/data/literature/"
    "PVRIG_case02_success_validation_series.csv"
)
AFFINITY_METRICS = Path(
    "/mnt/d/work/抗体/code/results/"
    "pvrig_positive11_structure_affinity_benchmark_20260719/"
    "final_evaluation_metrics.json"
)
V3_ROOT = Path("/mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714")
V3_RESULTS = V3_ROOT / "reports/job_results.tsv"
V3_EVALUATOR = V3_ROOT / "reports/EVALUATOR_STABLE.json"
REMOTE_V3_ROOT = Path(
    "/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_table(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_table(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def auc(positive: list[float], negative: list[float]) -> float:
    wins = 0
    ties = 0
    for pos_value in positive:
        for neg_value in negative:
            if pos_value > neg_value:
                wins += 1
            elif pos_value == neg_value:
                ties += 1
    return (wins + 0.5 * ties) / (len(positive) * len(negative))


def manifest_row(row: dict[str, str]) -> dict[str, object]:
    model = row["representative_model"]
    remote_path = (
        REMOTE_V3_ROOT
        / "runs"
        / row["job_id"]
        / "haddock_run"
        / "6_seletopclusts"
        / model
    )
    return {
        "job_id": row["job_id"],
        "entity_id": row["entity_id"],
        "control_class": row["control_class"],
        "expected_behavior": row["expected_behavior"],
        "conformation": row["conformation"],
        "docking_seed": row["seed"],
        "state": row["state"],
        "representative_model": model,
        "remote_representative_model_gz": str(remote_path),
        "job_hash": row["job_hash"],
        "representative_pair_label": row["representative_pair_label"],
        "model_strict_a_fraction": row["model_strict_a_fraction"],
        "haddock_score": row["haddock_score"],
        "native_hotspot_overlap": row["native_hotspot_overlap"],
        "cross_hotspot_overlap": row["cross_hotspot_overlap"],
        "native_total_occlusion": row["native_total_occlusion"],
        "cross_total_occlusion": row["cross_total_occlusion"],
        "native_cdr3_occlusion": row["native_cdr3_occlusion"],
        "cross_cdr3_occlusion": row["cross_cdr3_occlusion"],
    }


def entity_means(
    rows: list[dict[str, str]], feature
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["entity_id"]].append(feature(row))
    return {
        entity: statistics.mean(values)
        for entity, values in sorted(grouped.items())
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    positives = read_table(POSITIVE_SERIES)
    affinity = json.loads(AFFINITY_METRICS.read_text(encoding="utf-8"))
    v3_rows = read_table(V3_RESULTS, delimiter="\t")
    evaluator = json.loads(V3_EVALUATOR.read_text(encoding="utf-8"))

    successful_controls = [
        row
        for row in v3_rows
        if row["entity_type"] == "control" and row["state"] == "SUCCESS"
    ]
    patent_positive_jobs = [
        row
        for row in successful_controls
        if row["entity_id"].startswith("CTRL_PATENT_")
    ]
    destructive_jobs = [
        row
        for row in successful_controls
        if row["control_class"] == "destructive_alanine"
    ]

    if len(positives) != 11:
        raise ValueError(f"expected 11 positive VHHs, observed {len(positives)}")
    if len(patent_positive_jobs) != 66:
        raise ValueError(
            f"expected 66 positive V3 jobs, observed {len(patent_positive_jobs)}"
        )
    if len(destructive_jobs) != 84:
        raise ValueError(
            f"expected 84 destructive-control V3 jobs, observed "
            f"{len(destructive_jobs)}"
        )

    write_table(
        OUT / "positive_v3_job_manifest.tsv",
        [manifest_row(row) for row in patent_positive_jobs],
    )
    write_table(
        OUT / "destructive_control_v3_job_manifest.tsv",
        [manifest_row(row) for row in destructive_jobs],
    )

    feature_specs = {
        "strict_a_job_fraction": lambda row: (
            1.0 if row["representative_pair_label"] == "STRICT_A" else 0.0
        ),
        "model_strict_a_fraction": lambda row: float(
            row["model_strict_a_fraction"]
        ),
        "minimum_hotspot_overlap": lambda row: min(
            float(row["native_hotspot_overlap"]),
            float(row["cross_hotspot_overlap"]),
        ),
        "minimum_total_occlusion": lambda row: min(
            float(row["native_total_occlusion"]),
            float(row["cross_total_occlusion"]),
        ),
        "minimum_cdr3_occlusion": lambda row: min(
            float(row["native_cdr3_occlusion"]),
            float(row["cross_cdr3_occlusion"]),
        ),
        "minimum_cdr3_fraction": lambda row: min(
            float(row["native_cdr3_fraction"]),
            float(row["cross_cdr3_fraction"]),
        ),
        "negative_haddock_score": lambda row: -float(row["haddock_score"]),
    }
    observed_geometry = {}
    observed_rows = []
    for name, feature in feature_specs.items():
        positive_entity = entity_means(patent_positive_jobs, feature)
        destructive_entity = entity_means(destructive_jobs, feature)
        observed = {
            "positive_entity_count": len(positive_entity),
            "destructive_entity_count": len(destructive_entity),
            "positive_median": statistics.median(positive_entity.values()),
            "destructive_median": statistics.median(destructive_entity.values()),
            "entity_level_auc_positive_over_destructive": auc(
                list(positive_entity.values()),
                list(destructive_entity.values()),
            ),
        }
        observed_geometry[name] = observed
        observed_rows.append({"method": "V3_docking_geometry", "metric": name, **observed})
    write_table(OUT / "observed_method_performance.tsv", observed_rows)

    positive_panel = [
        {
            "molecule_name": row["molecule_name"],
            "family": row["family"],
            "blocking_ic50_nm": row["blocking_ic50_nm"] or None,
            "kd_m": row["kd_m"] or None,
            "experimental_role": row["validation_role"],
        }
        for row in positives
    ]

    md_pilot_pairs = [
        {
            "pair_id": "P20_F99A",
            "positive": "CTRL_PATENT_002_case02_pos_02_PVRIG-20",
            "control": "CTRL_MUTANT_003_mut_03_PVRIG-20_cdr3_arom_F99A",
        },
        {
            "pair_id": "P30_W100A",
            "positive": "CTRL_PATENT_003_case02_pos_03_PVRIG-30",
            "control": "CTRL_MUTANT_009_mut_09_PVRIG-30_cdr3_arom_W100A",
        },
        {
            "pair_id": "P38_F100A",
            "positive": "CTRL_PATENT_004_case02_pos_04_PVRIG-38",
            "control": "CTRL_MUTANT_014_mut_14_PVRIG-38_cdr3_arom_F100A",
        },
        {
            "pair_id": "P39_F99A",
            "positive": "CTRL_PATENT_005_case02_pos_05_PVRIG-39",
            "control": "CTRL_MUTANT_019_mut_19_PVRIG-39_cdr3_arom_F99A",
        },
    ]

    contract = {
        "contract_id": "pvrig_positive_control_energy_md_calibration_v1_20260724",
        "status": "READY_FOR_STATIC_EXTENSION_MD_TOPOLOGY_SMOKE_PENDING",
        "objective": (
            "Calibrate late-stage computational evidence against known PVRIG "
            "VHH positives without equating scores to experimental Kd or IC50."
        ),
        "official_alignment": {
            "target": "PVRIG extracellular domain at the PVRL2 interface",
            "initial_screen_score": {
                "BLI_single_concentration": 0.7,
                "expression_yield": 0.2,
                "purity": 0.1,
            },
            "rescreen_score": {"BLI_Kd_rank": 0.5, "competition_ELISA_IC50_rank": 0.5},
            "cdr_identity_rule": "each VHH CDR should be below 0.80 to known positives",
            "interpretation": (
                "Computational binding and blocking lanes are internal ranking "
                "priors only; wet-lab BLI and competition ELISA remain decisive."
            ),
        },
        "frozen_evidence": {
            "positive_panel": positive_panel,
            "positive_count": 11,
            "positive_with_kd": affinity["benchmark"]["known_kd_count"],
            "positive_with_blocking_ic50": sum(
                1 for row in positives if row["blocking_ic50_nm"]
            ),
            "old_affinity_pose_count": affinity["benchmark"]["existing_pose_count"],
            "v3_positive_jobs": len(patent_positive_jobs),
            "v3_destructive_control_jobs": len(destructive_jobs),
            "v3_total_jobs": evaluator["job_count"],
            "v3_successful_jobs": evaluator["completed_pose_backed_jobs"],
            "v3_geometry_discrimination": observed_geometry,
        },
        "observed_method_decisions": {
            "PRODIGY": {
                "role": "weak_pose_dependent_prior_only",
                "spearman_vs_experimental_pKd": affinity["prodigy_absolute"][
                    "spearman_vs_pKd"
                ],
                "median_absolute_pKd_error": affinity["prodigy_absolute"][
                    "median_absolute_pKd_error"
                ],
                "hard_gate": False,
            },
            "FoldX_AnalyseComplex": {
                "role": "not_for_cross_candidate_absolute_affinity",
                "spearman_vs_experimental_pKd": affinity["foldx_absolute"][
                    "spearman_vs_pKd"
                ],
                "hard_gate": False,
            },
            "FoldX_fixed_pose_ddG": {
                "role": "same_parent_diagnostic_only",
                "direction_correct": affinity["foldx_fixed_pose_relative"][
                    "ternary_direction_correct"
                ],
                "direction_total": affinity["foldx_fixed_pose_relative"][
                    "ternary_direction_total"
                ],
                "hard_gate": False,
            },
            "Graphinity": {
                "role": "rejected_for_current_multi_mutation_ranking",
                "direction_correct": affinity["graphinity"][
                    "ternary_direction_correct"
                ],
                "direction_total": affinity["graphinity"][
                    "ternary_direction_total"
                ],
                "hard_gate": False,
            },
            "Rosetta_InterfaceAnalyzer": {
                "role": "pending_same_panel_positive_control_extension",
                "hard_gate": False,
            },
            "MD_MMGBSA": {
                "role": "pending_paired_positive_control_calibration",
                "hard_gate": False,
            },
        },
        "calibration_design": {
            "positive_only_limitation": (
                "Positive-only data define a positive envelope but cannot "
                "estimate specificity or a false-positive rate."
            ),
            "control_boundary": (
                "The alanine mutants are computational perturbation controls, "
                "not experimentally confirmed non-binders/non-blockers."
            ),
            "cross_validation": "leave_one_family_out over 20/30/38/39/151 families",
            "replication": {
                "docking": "2 receptor conformations x 3 docking seeds",
                "MD": "3 independent velocity seeds per selected complex",
            },
        },
        "static_extension": {
            "panel": "66 positive jobs + 84 destructive-control jobs",
            "tools": ["PRODIGY", "FoldX AnalyseComplex", "Rosetta InterfaceAnalyzer"],
            "metrics": [
                "PRODIGY contact count and predicted deltaG as rank-only values",
                "FoldX interaction energy and clash/interface terms",
                "Rosetta interface dG, dSASA, shape complementarity, H-bonds, "
                "buried unsatisfied H-bonds and packstat",
            ],
            "method_acceptance": {
                "entity_level_auc_minimum": 0.70,
                "preferred_auc": 0.80,
                "known_positive_recall_minimum": 0.80,
                "maximum_control_false_positive_rate": 0.30,
                "leave_one_family_out_direction_consistency_minimum": 0.70,
                "rule": (
                    "A method failing these criteria remains descriptive and "
                    "must not become a hard gate."
                ),
            },
        },
        "md_pilot": {
            "stage_A_pairs": md_pilot_pairs,
            "official_anchor": "CTRL_PATENT_001_case02_pos_01_PVRIG-151_HR151",
            "pose_negative": (
                "Use a lower-support HR151 pose as a pose-stability control; "
                "do not label it a biological negative."
            ),
            "primary_engine": "GROMACS 2024.4 CUDA",
            "cross_engine_sentinel": "OpenMM 8.4 CUDA on HR151 and one paired control",
            "force_field": "CHARMM36m",
            "water": "TIP3P",
            "salt": "0.15 M NaCl",
            "time_step_fs": 2,
            "stage_A": "topology/minimization + 3 x 2 ns per system",
            "stage_B": "only if stage A is stable: 3 x 10-20 ns per retained system",
            "analysis_metrics": [
                "interface backbone RMSD",
                "VHH CDR3 RMSF",
                "PVRIG hotspot-contact occupancy",
                "PVRL2-interface occlusion persistence after reference overlay",
                "interface hydrogen-bond and salt-bridge occupancy",
                "interface SASA",
                "gmx_MMPBSA median and IQR from equilibrated snapshots",
            ],
            "trajectory_quality_gates": {
                "completed_replicates": "3/3",
                "no_broken_topology_or_periodic_boundary_artifact": True,
                "equilibration_window_fixed_before_label_analysis": True,
                "report_median_and_interquartile_range": True,
            },
            "method_acceptance": {
                "paired_direction_correct_minimum": "3/4 stage-A pairs",
                "known_positive_recall_minimum": 0.80,
                "entity_level_auc_minimum": 0.70,
                "seed_direction_agreement_minimum": "2/3",
                "rule": (
                    "Do not promote MD/MMGBSA to ranking until the frozen "
                    "paired panel passes; never convert MMGBSA to experimental Kd."
                ),
            },
        },
        "production_policy": {
            "large_scale": (
                "Sequence/developability and docking remain the scalable "
                "front end; static energy is applied to hundreds, MD only to "
                "roughly 20-50 finalists."
            ),
            "final_internal_ranking": (
                "Keep developability/expression-purity proxy, binding prior, "
                "blocking geometry and MD stability as separate evidence lanes."
            ),
            "known_positive_leakage": (
                "All exact/near known positives remain calibration or exclusion "
                "controls and are never submitted as novel candidates."
            ),
        },
        "input_hashes": {
            str(POSITIVE_SERIES): sha256(POSITIVE_SERIES),
            str(AFFINITY_METRICS): sha256(AFFINITY_METRICS),
            str(V3_RESULTS): sha256(V3_RESULTS),
            str(V3_EVALUATOR): sha256(V3_EVALUATOR),
        },
    }
    contract_path = OUT / "CALIBRATION_CONTRACT.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "status": "PASS",
        "contract": str(contract_path),
        "contract_sha256": sha256(contract_path),
        "positive_manifest_rows": len(patent_positive_jobs),
        "destructive_control_manifest_rows": len(destructive_jobs),
        "observed_method_rows": len(observed_rows),
    }
    (OUT / "BUILD_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
