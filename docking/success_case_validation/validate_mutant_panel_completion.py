#!/usr/bin/env python3
"""Validate full completion of the PVRIG mutant validation panel."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_ROOT = ROOT / "docking" / "calibration" / "mutant_validation_panel"
EXPECTED_RECORDS = 36
EXPECTED_LEAKAGE = Counter({"EXACT_KNOWN_POSITIVE": 7, "NEAR_KNOWN_POSITIVE": 29})
EXPECTED_CONSENSUS = Counter(
    {
        "CONSENSUS_BLOCKER_LIKE_A": 8,
        "SINGLE_BASELINE_BLOCKER_RECHECK": 109,
        "BLOCKER_PLAUSIBLE_B": 210,
        "EVIDENCE_INFERENCE_ONLY_E": 30,
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, default=DEFAULT_PANEL_ROOT)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--no-exact-consensus-assert", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def validate(panel_root: Path, exact_consensus: bool) -> tuple[list[str], dict[str, str], Counter[str]]:
    failures: list[str] = []
    status_path = panel_root / "mutant_panel_status.csv"
    leakage_path = panel_root / "mutant_panel_sequence_leakage.csv"
    panel_path = panel_root / "mutant_panel.csv"
    for path in [status_path, leakage_path, panel_path]:
        require(path.exists(), f"missing {path}", failures)
    if failures:
        return failures, {}, Counter()

    status_rows = read_csv(status_path)
    leakage_rows = read_csv(leakage_path)
    panel_rows = read_csv(panel_path)
    require(len(status_rows) == EXPECTED_RECORDS, f"status rows {len(status_rows)} != {EXPECTED_RECORDS}", failures)
    require(len(leakage_rows) == EXPECTED_RECORDS, f"leakage rows {len(leakage_rows)} != {EXPECTED_RECORDS}", failures)
    require(len(panel_rows) == EXPECTED_RECORDS, f"panel rows {len(panel_rows)} != {EXPECTED_RECORDS}", failures)

    required_yes = [
        "monomer_raw_pdb",
        "monomer_chainA_pdb",
        "structure_qc_sane",
        "haddock_run_dir",
        "classification_8x6b_csv",
        "classification_9e6y_csv",
        "consensus_csv",
    ]
    for column in required_yes:
        missing = [row["mutant_name"] for row in status_rows if row.get(column) != "yes"]
        require(not missing, f"{column} not yes for {missing}", failures)

    consensus = Counter()
    total_rows = 0
    short_consensus = []
    for row in status_rows:
        rows = int(row["consensus_rows"])
        total_rows += rows
        if rows < 5:
            short_consensus.append(row["mutant_name"])
        consensus["CONSENSUS_BLOCKER_LIKE_A"] += int(row["consensus_blocker_like_a"])
        consensus["SINGLE_BASELINE_BLOCKER_RECHECK"] += int(row["single_baseline_blocker_recheck"])
        consensus["BLOCKER_PLAUSIBLE_B"] += int(row["blocker_plausible_b"])
        consensus["EVIDENCE_INFERENCE_ONLY_E"] += int(row["evidence_inference_only_e"])
    require(not short_consensus, f"consensus rows <5 for {short_consensus}", failures)
    if exact_consensus:
        require(consensus == EXPECTED_CONSENSUS, f"consensus aggregate drift: {consensus} != {EXPECTED_CONSENSUS}", failures)

    leakage = Counter(row["leakage_label"] for row in leakage_rows)
    require(leakage == EXPECTED_LEAKAGE, f"leakage aggregate drift: {leakage} != {EXPECTED_LEAKAGE}", failures)

    metrics = {
        "panel_records": str(len(panel_rows)),
        "status_records": str(len(status_rows)),
        "leakage_records": str(len(leakage_rows)),
        "total_consensus_rows": str(total_rows),
        "consensus_blocker_like_a": str(consensus["CONSENSUS_BLOCKER_LIKE_A"]),
        "single_baseline_blocker_recheck": str(consensus["SINGLE_BASELINE_BLOCKER_RECHECK"]),
        "blocker_plausible_b": str(consensus["BLOCKER_PLAUSIBLE_B"]),
        "evidence_inference_only_e": str(consensus["EVIDENCE_INFERENCE_ONLY_E"]),
        "exact_known_positive": str(leakage["EXACT_KNOWN_POSITIVE"]),
        "near_known_positive": str(leakage["NEAR_KNOWN_POSITIVE"]),
        "failures": str(len(failures)),
    }
    return failures, metrics, consensus


def write_report(path: Path, failures: list[str], metrics: dict[str, str]) -> None:
    verdict = "PASS" if not failures else "FAIL"
    lines = [
        "# Mutant Panel Completion Validation",
        "",
        f"Verdict: {verdict}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Failures", ""])
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This validates computational completion and current aggregate labels for the mutant/control panel.",
            "- These rows are leakage/robustness controls derived from known positives, not new design submissions.",
            "- Experimental blocking still requires assays; single-baseline A remains a recheck label.",
            "- Run `summarize_mutant_panel_results.py` to stratify retained A signals and identify CDR3 disruptive/alanine manual-review rows.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    panel_root = args.panel_root.resolve()
    failures, metrics, _consensus = validate(panel_root, not args.no_exact_consensus_assert)
    out_md = args.out_md or panel_root / "MUTANT_PANEL_COMPLETION_VALIDATION.md"
    write_report(out_md, failures, metrics)
    if failures:
        print("FAIL mutant panel completion validation")
        for failure in failures[:20]:
            print(f"failure={failure}")
        print(f"out_md={out_md}")
        raise SystemExit(1)
    print("OK mutant panel completion validated")
    for key, value in metrics.items():
        print(f"{key}={value}")
    print(f"out_md={out_md}")


if __name__ == "__main__":
    main()
