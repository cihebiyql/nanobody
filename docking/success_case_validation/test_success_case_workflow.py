#!/usr/bin/env python3
"""Regression test for the success-case blocker judgment workflow."""

from __future__ import annotations

import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "docking" / "success_case_validation"
OUT_DIR = WORKFLOW_DIR / "test_outputs"


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def assert_equal(got: object, expected: object, message: str) -> None:
    if got != expected:
        raise AssertionError(f"{message}: got {got!r}, expected {expected!r}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "hr151_positive_control_reclassified.csv"
    out_md = OUT_DIR / "hr151_positive_control_reclassified.md"
    consensus_csv = OUT_DIR / "hr151_positive_control_multibaseline_consensus.csv"
    consensus_md = OUT_DIR / "hr151_positive_control_multibaseline_consensus.md"

    run([sys.executable, str(ROOT / "docking/scripts/test_align_pdb_by_chain.py")])
    run([sys.executable, str(WORKFLOW_DIR / "validate_success_case_standards.py")])
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "apply_blocker_judgment.py"),
            "--occlusion-csv",
            str(ROOT / "docking/case02_hr151_pvrig/reports/cdr_region_occlusion/cdr3_occlusion_summary.csv"),
            "--mechanism-csv",
            str(ROOT / "docking/case02_hr151_pvrig/reports/haddock3_top_model_mechanism_scores.csv"),
            "--candidate-name",
            "HR151_positive_control",
            "--format-context",
            "naked_vhh",
            "--out-csv",
            str(out_csv),
            "--out-md",
            str(out_md),
        ]
    )

    rows = read_rows(out_csv)
    counts = Counter(row["blocker_class"] for row in rows)
    assert_equal(counts["BLOCKER_LIKE_A"], 4, "HR-151 positive-control blocker-like pose count")
    assert_equal(counts["BINDER_LIKE_C"], 1, "HR-151 internal binder-like negative-control pose count")

    by_model = {row["model"]: row["blocker_class"] for row in rows}
    expected = {
        "cluster_1_model_1": "BLOCKER_LIKE_A",
        "cluster_3_model_1": "BLOCKER_LIKE_A",
        "cluster_8_model_1": "BLOCKER_LIKE_A",
        "cluster_10_model_1": "BLOCKER_LIKE_A",
        "cluster_2_model_1": "BINDER_LIKE_C",
    }
    assert_equal(by_model, expected, "HR-151 reclassification model map")

    previous_rows = read_rows(ROOT / "docking/case02_hr151_pvrig/reports/hr151_positive_control_blocker_classification.csv")
    previous = {row["model"]: row["classification"] for row in previous_rows}
    assert_equal(by_model, previous, "new classifier matches previous HR-151 classification artifact")

    report = out_md.read_text(encoding="utf-8")
    if "BLOCKER_LIKE_A: 4" not in report or "BINDER_LIKE_C: 1" not in report:
        raise AssertionError("Markdown report is missing expected summary counts")

    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "summarize_multibaseline_judgment.py"),
            "--classification",
            f"8x6b={out_csv}",
            "--candidate-name",
            "HR151_positive_control",
            "--out-csv",
            str(consensus_csv),
            "--out-md",
            str(consensus_md),
        ]
    )
    consensus_rows = read_rows(consensus_csv)
    consensus_counts = Counter(row["consensus_class"] for row in consensus_rows)
    assert_equal(
        consensus_counts["SINGLE_BASELINE_BLOCKER_RECHECK"],
        4,
        "single-baseline HR-151 blocker recheck count",
    )
    assert_equal(
        consensus_counts["SINGLE_BASELINE_BINDER_LIKE_C"],
        1,
        "single-baseline HR-151 binder-like count",
    )

    print("OK success-case workflow regression test passed")


if __name__ == "__main__":
    main()
