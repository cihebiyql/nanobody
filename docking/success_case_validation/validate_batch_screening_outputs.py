#!/usr/bin/env python3
"""Validate completed batch outputs for the PVRIG VHH blocker-screening workflow."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH_ROOT = ROOT / "docking" / "calibration" / "patent_success_validation"
EXPECTED_IDS = [
    "PVRIG-151_HR151",
    "PVRIG-20",
    "PVRIG-30",
    "PVRIG-38",
    "PVRIG-39",
    "20H5",
    "30H2",
    "39H2",
    "39H4",
    "151H7",
    "151H8",
]
EXPECTED_FAMILIES = Counter({"151": 3, "20": 2, "30": 2, "39": 3, "38": 1})
EXPECTED_CONSENSUS_COUNTS = Counter(
    {
        "CONSENSUS_BLOCKER_LIKE_A": 3,
        "SINGLE_BASELINE_BLOCKER_RECHECK": 36,
        "BLOCKER_PLAUSIBLE_B": 57,
        "EVIDENCE_INFERENCE_ONLY_E": 13,
    }
)
REQUIRED_STATUS_COLUMNS = [
    "input_fasta",
    "cdr_ambig_tbl",
    "haddock_cfg",
    "node1_structure_script",
    "node1_haddock_script",
    "monomer_raw_pdb",
    "monomer_chainA_pdb",
    "haddock_run_dir",
    "consensus_csv",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument(
        "--strict-manifest-status",
        action="store_true",
        help="Fail if batch_manifest status columns still say pending.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check_file(path: Path, failures: list[str]) -> None:
    if not path.exists():
        failures.append(f"missing file: {path}")


def collect(batch_root: Path, strict_manifest_status: bool) -> tuple[list[str], list[str], dict[str, str]]:
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, str] = {}
    manifest_path = batch_root / "batch_manifest.csv"
    status_path = batch_root / "batch_status.csv"
    summary_path = batch_root / "batch_consensus_summary.csv"
    cdr_ranges_path = batch_root / "patent_success_validation_cdr_ranges.csv"
    check_file(manifest_path, failures)
    check_file(status_path, failures)
    check_file(summary_path, failures)
    check_file(cdr_ranges_path, failures)
    if failures:
        return failures, warnings, metrics

    manifest_rows = read_csv(manifest_path)
    status_rows = read_csv(status_path)
    summary_rows = read_csv(summary_path)
    ordered_ids = [row["molecule_name"] for row in sorted(manifest_rows, key=lambda row: int(row["recommended_order"]))]
    status_ids = [row["molecule_name"] for row in sorted(status_rows, key=lambda row: int(row["recommended_order"]))]
    summary_ids = [row["molecule_name"] for row in sorted(summary_rows, key=lambda row: int(row["recommended_order"]))]
    require(ordered_ids == EXPECTED_IDS, f"unexpected manifest order: {ordered_ids}")
    require(status_ids == EXPECTED_IDS, f"unexpected status order: {status_ids}")
    require(summary_ids == EXPECTED_IDS, f"unexpected summary order: {summary_ids}")
    require(Counter(row["family"] for row in manifest_rows) == EXPECTED_FAMILIES, "unexpected manifest family coverage")
    require(Counter(row["family"] for row in summary_rows) == EXPECTED_FAMILIES, "unexpected summary family coverage")

    for row in manifest_rows:
        if "not_new_design" not in row.get("usage_boundary", ""):
            failures.append(f"usage boundary missing not_new_design: {row['molecule_name']}")
        if row.get("cdr_exact_match_status") != "exact":
            failures.append(f"raw CDR exact match failed: {row['molecule_name']}")
        stale = [key for key in ["structure_status", "docking_status", "consensus_status"] if row.get(key) == "pending"]
        if stale:
            message = f"manifest status columns still pending for {row['molecule_name']}: {','.join(stale)}"
            if strict_manifest_status:
                failures.append(message)
            else:
                warnings.append(message)

    for row in status_rows:
        for column in REQUIRED_STATUS_COLUMNS:
            if row.get(column) != "yes":
                failures.append(f"status {column} != yes for {row['molecule_name']}")

    aggregate = Counter()
    pose_total = 0
    for row in summary_rows:
        workdir = Path(row["workdir"])
        name = next(item["calibration_name"] for item in manifest_rows if item["molecule_name"] == row["molecule_name"])
        check_file(workdir / "inputs" / f"{name}_vhh.fasta", failures)
        if not (workdir / "inputs" / f"{name}_cdr_ranges.csv").exists():
            warnings.append(
                f"per-case cdr range CSV absent for {row['molecule_name']}; using batch-level patent_success_validation_cdr_ranges.csv"
            )
        check_file(workdir / "haddock3" / "data" / f"{name}_cdr_to_pvrig_hotspot_ambig.tbl", failures)
        check_file(workdir / "monomer" / f"{name}_nanobodybuilder2.pdb", failures)
        check_file(workdir / "haddock3" / "data" / f"{name}_vhh_chainA.pdb", failures)
        check_file(workdir / "haddock3" / f"run_{name}_pvrig_hotspot_test", failures)
        reports = workdir / "reports"
        check_file(reports / f"{name}_8x6b_blocker_classification.csv", failures)
        check_file(reports / f"{name}_9e6y_blocker_classification.csv", failures)
        check_file(reports / f"{name}_8x6b_9e6y_consensus.csv", failures)
        consensus_rows = read_csv(reports / f"{name}_8x6b_9e6y_consensus.csv") if (reports / f"{name}_8x6b_9e6y_consensus.csv").exists() else []
        if str(len(consensus_rows)) != row["pose_count"]:
            failures.append(f"pose_count mismatch for {row['molecule_name']}: summary={row['pose_count']} file={len(consensus_rows)}")
        pose_total += int(row["pose_count"])
        aggregate["CONSENSUS_BLOCKER_LIKE_A"] += int(row["consensus_blocker_like_a"])
        aggregate["SINGLE_BASELINE_BLOCKER_RECHECK"] += int(row["single_baseline_blocker_recheck"])
        aggregate["BLOCKER_PLAUSIBLE_B"] += int(row["blocker_plausible_b"])
        aggregate["EVIDENCE_INFERENCE_ONLY_E"] += int(row["evidence_inference_only_e"])

    require(pose_total == 109, f"unexpected total pose count: {pose_total}")
    require(aggregate == EXPECTED_CONSENSUS_COUNTS, f"unexpected consensus aggregate: {aggregate}")
    strong_20h5 = next(row for row in summary_rows if row["molecule_name"] == "20H5")
    require(int(strong_20h5["consensus_blocker_like_a"]) >= 3, "20H5 lost consensus-A evidence")
    non_151 = {row["molecule_name"] for row in summary_rows if row["family"] != "151"}
    require({"PVRIG-20", "PVRIG-30", "PVRIG-38", "PVRIG-39", "20H5", "30H2", "39H2", "39H4"}.issubset(non_151), "non-151 controls missing")

    metrics.update(
        {
            "manifest_rows": str(len(manifest_rows)),
            "status_rows": str(len(status_rows)),
            "summary_rows": str(len(summary_rows)),
            "pose_total": str(pose_total),
            "consensus_blocker_like_a": str(aggregate["CONSENSUS_BLOCKER_LIKE_A"]),
            "single_baseline_blocker_recheck": str(aggregate["SINGLE_BASELINE_BLOCKER_RECHECK"]),
            "blocker_plausible_b": str(aggregate["BLOCKER_PLAUSIBLE_B"]),
            "evidence_inference_only_e": str(aggregate["EVIDENCE_INFERENCE_ONLY_E"]),
            "families": ";".join(f"{key}:{value}" for key, value in sorted(EXPECTED_FAMILIES.items())),
            "warnings": str(len(warnings)),
            "failures": str(len(failures)),
        }
    )
    return failures, warnings, metrics


def write_report(path: Path, failures: list[str], warnings: list[str], metrics: dict[str, str]) -> None:
    verdict = "PASS" if not failures else "FAIL"
    lines = [
        "# Batch Screening Output Integrity Report",
        "",
        f"Verdict: {verdict}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {item}" for item in warnings[:50])
        if len(warnings) > 50:
            lines.append(f"- ... {len(warnings) - 50} more warnings")
    else:
        lines.append("- none")
    lines.extend(["", "## Failures", ""])
    if failures:
        lines.extend(f"- {item}" for item in failures[:50])
        if len(failures) > 50:
            lines.append(f"- ... {len(failures) - 50} more failures")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This validates batch artifact completeness and locked aggregate counts for the completed 11-positive calibration set.",
            "- Warnings about pending manifest status columns are documentation drift; batch_status.csv and the actual output files are the execution truth.",
            "- This does not claim experimental blocking for new sequences; new or mutated VHHs still require structure prediction, docking, and postprocessing.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    batch_root = args.batch_root.resolve()
    failures, warnings, metrics = collect(batch_root, args.strict_manifest_status)
    out_md = args.out_md or batch_root / "BATCH_OUTPUT_INTEGRITY_REPORT.md"
    write_report(out_md, failures, warnings, metrics)
    if failures:
        print("FAIL batch screening outputs")
        for failure in failures[:20]:
            print(f"failure={failure}")
        print(f"out_md={out_md}")
        raise SystemExit(1)
    print("OK batch screening outputs validated")
    for key in [
        "manifest_rows",
        "summary_rows",
        "pose_total",
        "consensus_blocker_like_a",
        "single_baseline_blocker_recheck",
        "blocker_plausible_b",
        "evidence_inference_only_e",
        "warnings",
    ]:
        print(f"{key}={metrics.get(key, '')}")
    print(f"out_md={out_md}")


if __name__ == "__main__":
    main()
