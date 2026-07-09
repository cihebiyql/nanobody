#!/usr/bin/env python3
"""Fast robustness regression tests for the PVRIG VHH blocker-screening workflow."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "docking" / "success_case_validation"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(str(item) for item in cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def assert_equal(got: object, expected: object, message: str) -> None:
    if got != expected:
        raise AssertionError(f"{message}: got {got!r}, expected {expected!r}")


def test_classifier_boundaries(tmp: Path) -> None:
    fields = [
        "model",
        "hotspot_overlap_count",
        "total_vhh_pvrl2_residue_pair_occlusion",
        "cdr3_pvrl2_residue_pair_occlusion",
        "cdr3_occlusion_fraction",
        "framework_residue_pair_occlusion",
    ]
    rows = [
        {"model": "exact_A", "hotspot_overlap_count": "14", "total_vhh_pvrl2_residue_pair_occlusion": "500", "cdr3_pvrl2_residue_pair_occlusion": "100", "cdr3_occlusion_fraction": "0.15", "framework_residue_pair_occlusion": "0"},
        {"model": "hotspot_13", "hotspot_overlap_count": "13", "total_vhh_pvrl2_residue_pair_occlusion": "500", "cdr3_pvrl2_residue_pair_occlusion": "100", "cdr3_occlusion_fraction": "0.15", "framework_residue_pair_occlusion": "0"},
        {"model": "total_499", "hotspot_overlap_count": "14", "total_vhh_pvrl2_residue_pair_occlusion": "499", "cdr3_pvrl2_residue_pair_occlusion": "100", "cdr3_occlusion_fraction": "0.15", "framework_residue_pair_occlusion": "0"},
        {"model": "cdr3_99", "hotspot_overlap_count": "14", "total_vhh_pvrl2_residue_pair_occlusion": "500", "cdr3_pvrl2_residue_pair_occlusion": "99", "cdr3_occlusion_fraction": "0.15", "framework_residue_pair_occlusion": "0"},
        {"model": "fraction_0149", "hotspot_overlap_count": "14", "total_vhh_pvrl2_residue_pair_occlusion": "500", "cdr3_pvrl2_residue_pair_occlusion": "100", "cdr3_occlusion_fraction": "0.149", "framework_residue_pair_occlusion": "0"},
        {"model": "binder_49", "hotspot_overlap_count": "14", "total_vhh_pvrl2_residue_pair_occlusion": "49", "cdr3_pvrl2_residue_pair_occlusion": "0", "cdr3_occlusion_fraction": "0", "framework_residue_pair_occlusion": "0"},
        {"model": "binder_boundary_50", "hotspot_overlap_count": "14", "total_vhh_pvrl2_residue_pair_occlusion": "50", "cdr3_pvrl2_residue_pair_occlusion": "0", "cdr3_occlusion_fraction": "0", "framework_residue_pair_occlusion": "0"},
    ]
    occlusion = tmp / "boundary_occlusion.csv"
    out_csv = tmp / "boundary_classified.csv"
    write_csv(occlusion, rows, fields)
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "apply_blocker_judgment.py"),
            "--occlusion-csv",
            str(occlusion),
            "--out-csv",
            str(out_csv),
            "--candidate-name",
            "boundary_test",
        ]
    )
    observed = {row["model"]: row["blocker_class"] for row in read_csv(out_csv)}
    expected = {
        "exact_A": "BLOCKER_LIKE_A",
        "hotspot_13": "BLOCKER_PLAUSIBLE_B",
        "total_499": "BLOCKER_PLAUSIBLE_B",
        "cdr3_99": "BLOCKER_PLAUSIBLE_B",
        "fraction_0149": "BLOCKER_PLAUSIBLE_B",
        "binder_49": "BINDER_LIKE_C",
        "binder_boundary_50": "EVIDENCE_INFERENCE_ONLY_E",
    }
    assert_equal(observed, expected, "classifier threshold boundary map")


def test_consensus_branches(tmp: Path) -> None:
    fields = ["model", "haddock_rank", "blocker_class"]
    base1 = tmp / "baseline1.csv"
    base2 = tmp / "baseline2.csv"
    rows1 = [
        {"model": "aa", "haddock_rank": "1", "blocker_class": "BLOCKER_LIKE_A"},
        {"model": "ac", "haddock_rank": "2", "blocker_class": "BLOCKER_LIKE_A"},
        {"model": "bc", "haddock_rank": "3", "blocker_class": "BLOCKER_PLAUSIBLE_B"},
        {"model": "cc", "haddock_rank": "4", "blocker_class": "BINDER_LIKE_C"},
        {"model": "bb", "haddock_rank": "5", "blocker_class": "BLOCKER_PLAUSIBLE_B"},
        {"model": "ee", "haddock_rank": "6", "blocker_class": "EVIDENCE_INFERENCE_ONLY_E"},
    ]
    rows2 = [
        {"model": "aa", "haddock_rank": "1", "blocker_class": "BLOCKER_LIKE_A"},
        {"model": "ac", "haddock_rank": "2", "blocker_class": "BINDER_LIKE_C"},
        {"model": "bc", "haddock_rank": "3", "blocker_class": "BINDER_LIKE_C"},
        {"model": "cc", "haddock_rank": "4", "blocker_class": "BINDER_LIKE_C"},
        {"model": "bb", "haddock_rank": "5", "blocker_class": "BLOCKER_PLAUSIBLE_B"},
        {"model": "ee", "haddock_rank": "6", "blocker_class": "EVIDENCE_INFERENCE_ONLY_E"},
    ]
    write_csv(base1, rows1, fields)
    write_csv(base2, rows2, fields)
    out_csv = tmp / "consensus.csv"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "summarize_multibaseline_judgment.py"),
            "--classification",
            f"b1={base1}",
            "--classification",
            f"b2={base2}",
            "--out-csv",
            str(out_csv),
            "--candidate-name",
            "consensus_branch_test",
        ]
    )
    observed = {row["model"]: row["consensus_class"] for row in read_csv(out_csv)}
    expected = {
        "aa": "CONSENSUS_BLOCKER_LIKE_A",
        "ac": "DISCORDANT_REDOCK_REQUIRED",
        "bc": "DISCORDANT_PLAUSIBLE_VS_BINDER_RECHECK",
        "cc": "CONSENSUS_BINDER_LIKE_C",
        "bb": "BLOCKER_PLAUSIBLE_B",
        "ee": "EVIDENCE_INFERENCE_ONLY_E",
    }
    assert_equal(observed, expected, "dual-baseline consensus branch map")

    single_csv = tmp / "single.csv"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "summarize_multibaseline_judgment.py"),
            "--classification",
            f"b1={base1}",
            "--out-csv",
            str(single_csv),
            "--candidate-name",
            "single_branch_test",
        ]
    )
    single = {row["model"]: row["consensus_class"] for row in read_csv(single_csv)}
    assert_equal(single["aa"], "SINGLE_BASELINE_BLOCKER_RECHECK", "single-baseline A branch")
    assert_equal(single["cc"], "SINGLE_BASELINE_BINDER_LIKE_C", "single-baseline C branch")


def test_batch_integrity_and_threshold_sensitivity(tmp: Path) -> None:
    integrity_md = tmp / "integrity.md"
    run([sys.executable, str(WORKFLOW_DIR / "validate_batch_screening_outputs.py"), "--out-md", str(integrity_md)])
    threshold_csv = tmp / "threshold.csv"
    threshold_md = tmp / "threshold.md"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "analyze_threshold_sensitivity.py"),
            "--out-csv",
            str(threshold_csv),
            "--out-md",
            str(threshold_md),
        ]
    )
    default_rows = [
        row
        for row in read_csv(threshold_csv)
        if row["hotspot_min"] == "14" and row["total_min"] == "500" and row["cdr3_min"] == "100" and row["cdr3_fraction_min"] == "0.15"
    ]
    assert_equal(len(default_rows), 1, "default threshold row count")
    default = default_rows[0]
    assert_equal(default["total_consensus_rows"], "109", "threshold default total rows")
    assert_equal(default["consensus_blocker_like_a"], "3", "threshold default consensus A count")
    assert_equal(default["single_baseline_blocker_recheck"], "36", "threshold default single-baseline count")
    assert_equal(default["blocker_plausible_b"], "57", "threshold default plausible count")
    assert_equal(default["evidence_inference_only_e"], "13", "threshold default evidence-only count")

    mutant_threshold_csv = tmp / "mutant_threshold.csv"
    mutant_threshold_md = tmp / "mutant_threshold.md"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "analyze_mutant_panel_threshold_sensitivity.py"),
            "--out-csv",
            str(mutant_threshold_csv),
            "--out-md",
            str(mutant_threshold_md),
        ]
    )
    mutant_defaults = [
        row
        for row in read_csv(mutant_threshold_csv)
        if row["hotspot_min"] == "14" and row["total_min"] == "500" and row["cdr3_min"] == "100" and row["cdr3_fraction_min"] == "0.15"
    ]
    assert_equal(len(mutant_defaults), 1, "mutant default threshold row count")
    mutant_default = mutant_defaults[0]
    assert_equal(mutant_default["total_consensus_rows"], "357", "mutant threshold default total rows")
    assert_equal(mutant_default["consensus_blocker_like_a"], "8", "mutant threshold default consensus A count")
    assert_equal(mutant_default["single_baseline_blocker_recheck"], "109", "mutant threshold default single-baseline count")
    assert_equal(mutant_default["blocker_plausible_b"], "210", "mutant threshold default plausible count")
    assert_equal(mutant_default["evidence_inference_only_e"], "30", "mutant threshold default evidence-only count")
    assert_equal(mutant_default["disruptive_controls_with_any_a_signal"], "12", "mutant disruptive retained-A count")


def test_candidate_scaffold_tempdir(tmp: Path) -> None:
    manifest = {row["molecule_name"]: row for row in read_csv(ROOT / "docking/calibration/patent_success_validation/batch_manifest.csv")}
    seq = next(
        row["sequence"]
        for row in read_csv(ROOT / "机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_sequence_mapping.csv")
        if row["molecule_name"] == "PVRIG-20"
    )
    base = manifest["PVRIG-20"]
    out_root = tmp / "candidate_scaffold"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "prepare_candidate_sequence_workflow.py"),
            "--name",
            "Smoke Mutant/Bad Name",
            "--sequence",
            seq,
            "--out-root",
            str(out_root),
            "--cdr1",
            base["cdr1_range"],
            "--cdr2",
            base["cdr2_range"],
            "--cdr3",
            base["cdr3_range"],
            "--haddock-sampling",
            "4",
            "--top-models",
            "2",
        ]
    )
    workdir = out_root / "Smoke_Mutant_Bad_Name"
    for relative in [
        "inputs/Smoke_Mutant_Bad_Name_vhh.fasta",
        "inputs/Smoke_Mutant_Bad_Name_cdr_ranges.csv",
        "haddock3/Smoke_Mutant_Bad_Name_pvrig_hotspot_test.cfg",
        "haddock3/data/Smoke_Mutant_Bad_Name_cdr_to_pvrig_hotspot_ambig.tbl",
        "run_node1_structure_prediction.sh",
        "run_node1_haddock3.sh",
        "postprocess_after_docking.sh",
        "README.md",
    ]:
        if not (workdir / relative).exists():
            raise AssertionError(f"candidate scaffold missing {relative}")
    cfg = (workdir / "haddock3/Smoke_Mutant_Bad_Name_pvrig_hotspot_test.cfg").read_text(encoding="utf-8")
    if "sampling = 4" not in cfg or "top_models = 2" not in cfg:
        raise AssertionError("candidate scaffold did not preserve requested sampling/top-model settings")


def test_mutant_panel_leakage_gate(tmp: Path) -> None:
    out_root = tmp / "mutant_panel"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "prepare_mutant_validation_batch.py"),
            "--out-root",
            str(out_root),
            "--limit",
            "6",
        ]
    )
    leakage_csv = tmp / "mutant_panel_leakage.csv"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "check_vhh_sequence_leakage.py"),
            "--candidate-csv",
            str(out_root / "mutant_panel.csv"),
            "--out-csv",
            str(leakage_csv),
        ]
    )
    labels = [row["leakage_label"] for row in read_csv(leakage_csv)]
    assert_equal(labels.count("EXACT_KNOWN_POSITIVE"), 1, "mutant panel exact positive leakage controls")
    assert_equal(labels.count("NEAR_KNOWN_POSITIVE"), 5, "mutant panel near-positive perturbation controls")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pvrig_robustness_tests_") as tmpdir:
        tmp = Path(tmpdir)
        test_classifier_boundaries(tmp)
        test_consensus_branches(tmp)
        test_batch_integrity_and_threshold_sensitivity(tmp)
        test_candidate_scaffold_tempdir(tmp)
        test_mutant_panel_leakage_gate(tmp)
    print("OK blocker screening robustness tests passed")


if __name__ == "__main__":
    main()
