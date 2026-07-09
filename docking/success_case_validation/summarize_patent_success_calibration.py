#!/usr/bin/env python3
"""Summarize the WO2021180205A1 patent success-series calibration batch."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH_ROOT = ROOT / "docking" / "calibration" / "patent_success_validation"

SUMMARY_FIELDS = [
    "recommended_order",
    "molecule_name",
    "family",
    "blocking_ic50_nm",
    "kd_m",
    "workdir",
    "pose_count",
    "case_level_call",
    "consensus_blocker_like_a",
    "single_baseline_blocker_recheck",
    "blocker_plausible_b",
    "evidence_inference_only_e",
    "top_model",
    "top_model_consensus_class",
    "top_model_baseline_classes",
    "top_8x6b_class",
    "top_8x6b_hotspot",
    "top_8x6b_total_occlusion",
    "top_8x6b_cdr3_occlusion",
    "top_8x6b_cdr3_fraction",
    "top_9e6y_class",
    "top_9e6y_hotspot",
    "top_9e6y_total_occlusion",
    "top_9e6y_cdr3_occlusion",
    "top_9e6y_cdr3_fraction",
    "consensus_csv",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    parser.add_argument("--out-csv", type=Path)
    parser.add_argument("--out-md", type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def first_by_model(rows: list[dict[str, str]], model: str) -> dict[str, str]:
    return next((row for row in rows if row.get("model") == model), rows[0] if rows else {})


def case_level_call(counts: Counter[str]) -> str:
    if counts["CONSENSUS_BLOCKER_LIKE_A"]:
        return "HAS_CONSENSUS_BLOCKER_LIKE_A"
    if counts["SINGLE_BASELINE_BLOCKER_RECHECK"]:
        return "HAS_SINGLE_BASELINE_BLOCKER_RECHECK"
    if counts["BLOCKER_PLAUSIBLE_B"]:
        return "BLOCKER_PLAUSIBLE_B_ONLY"
    if counts["EVIDENCE_INFERENCE_ONLY_E"]:
        return "EVIDENCE_INFERENCE_ONLY_E_ONLY"
    return "NO_USABLE_CONSENSUS_ROWS"


def build_rows(batch_root: Path) -> list[dict[str, str]]:
    manifest = batch_root / "batch_manifest.csv"
    if not manifest.exists():
        raise SystemExit(f"missing batch manifest: {manifest}")

    output: list[dict[str, str]] = []
    for item in read_csv(manifest):
        workdir = Path(item["workdir"])
        name = item["calibration_name"]
        consensus_csv = workdir / "reports" / f"{name}_8x6b_9e6y_consensus.csv"
        class_8 = workdir / "reports" / f"{name}_8x6b_blocker_classification.csv"
        class_9 = workdir / "reports" / f"{name}_9e6y_blocker_classification.csv"
        if not consensus_csv.exists():
            raise SystemExit(f"missing consensus CSV: {consensus_csv}")
        consensus_rows = read_csv(consensus_csv)
        counts = Counter(row.get("consensus_class", "") for row in consensus_rows)
        top = consensus_rows[0] if consensus_rows else {}
        top_model = top.get("model", "")
        top_8 = first_by_model(read_csv(class_8), top_model) if class_8.exists() else {}
        top_9 = first_by_model(read_csv(class_9), top_model) if class_9.exists() else {}
        output.append(
            {
                "recommended_order": item["recommended_order"],
                "molecule_name": item["molecule_name"],
                "family": item["family"],
                "blocking_ic50_nm": item.get("blocking_ic50_nm", ""),
                "kd_m": item.get("kd_m", ""),
                "workdir": str(workdir),
                "pose_count": str(len(consensus_rows)),
                "case_level_call": case_level_call(counts),
                "consensus_blocker_like_a": str(counts["CONSENSUS_BLOCKER_LIKE_A"]),
                "single_baseline_blocker_recheck": str(counts["SINGLE_BASELINE_BLOCKER_RECHECK"]),
                "blocker_plausible_b": str(counts["BLOCKER_PLAUSIBLE_B"]),
                "evidence_inference_only_e": str(counts["EVIDENCE_INFERENCE_ONLY_E"]),
                "top_model": top_model,
                "top_model_consensus_class": top.get("consensus_class", ""),
                "top_model_baseline_classes": top.get("baseline_classes", ""),
                "top_8x6b_class": top_8.get("blocker_class", ""),
                "top_8x6b_hotspot": top_8.get("hotspot_overlap_count", ""),
                "top_8x6b_total_occlusion": top_8.get("total_vhh_pvrl2_residue_pair_occlusion", ""),
                "top_8x6b_cdr3_occlusion": top_8.get("cdr3_pvrl2_residue_pair_occlusion", ""),
                "top_8x6b_cdr3_fraction": top_8.get("cdr3_occlusion_fraction", ""),
                "top_9e6y_class": top_9.get("blocker_class", ""),
                "top_9e6y_hotspot": top_9.get("hotspot_overlap_count", ""),
                "top_9e6y_total_occlusion": top_9.get("total_vhh_pvrl2_residue_pair_occlusion", ""),
                "top_9e6y_cdr3_occlusion": top_9.get("cdr3_pvrl2_residue_pair_occlusion", ""),
                "top_9e6y_cdr3_fraction": top_9.get("cdr3_occlusion_fraction", ""),
                "consensus_csv": str(consensus_csv),
            }
        )
    return output


def write_md(path: Path, rows: list[dict[str, str]]) -> None:
    aggregate = Counter()
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        aggregate["poses"] += int(row["pose_count"])
        aggregate["CONSENSUS_BLOCKER_LIKE_A"] += int(row["consensus_blocker_like_a"])
        aggregate["SINGLE_BASELINE_BLOCKER_RECHECK"] += int(row["single_baseline_blocker_recheck"])
        aggregate["BLOCKER_PLAUSIBLE_B"] += int(row["blocker_plausible_b"])
        aggregate["EVIDENCE_INFERENCE_ONLY_E"] += int(row["evidence_inference_only_e"])
        family_counts[row["family"]][row["case_level_call"]] += 1

    lines = [
        "# Patent Success Series Postprocess Summary",
        "",
        "Updated: 2026-07-08",
        "",
        "## Bottom line",
        "",
        "- The 11 WO2021180205A1 positive-control VHH/HCVR sequences now all have monomer structures, HADDOCK3 run directories, 8X6B scoring, 9E6Y scoring, and multi-baseline consensus CSVs.",
        "- The calibration is no longer HR-151-only: families 20, 30, 38, 39, and 151 all have completed postprocessing.",
        "- These sequences remain positive controls and leakage references, not new design candidates.",
        "- The computational label means blocker-like geometry or follow-up priority; it is not experimental proof of PVRIG-PVRL2 blocking.",
        "",
        "## Aggregate pose labels",
        "",
        f"- Total cases: {len(rows)}",
        f"- Total poses summarized: {aggregate['poses']}",
        f"- CONSENSUS_BLOCKER_LIKE_A: {aggregate['CONSENSUS_BLOCKER_LIKE_A']}",
        f"- SINGLE_BASELINE_BLOCKER_RECHECK: {aggregate['SINGLE_BASELINE_BLOCKER_RECHECK']}",
        f"- BLOCKER_PLAUSIBLE_B: {aggregate['BLOCKER_PLAUSIBLE_B']}",
        f"- EVIDENCE_INFERENCE_ONLY_E: {aggregate['EVIDENCE_INFERENCE_ONLY_E']}",
        "",
        "## Family coverage",
        "",
        "| family | completed cases | case-level calls |",
        "| --- | ---: | --- |",
    ]
    families = sorted({row["family"] for row in rows})
    for family in families:
        calls = family_counts[family]
        call_text = "; ".join(f"{key}={value}" for key, value in sorted(calls.items()))
        lines.append(f"| {family} | {sum(calls.values())} | {call_text} |")

    lines.extend(
        [
            "",
            "## Per-sequence calibration summary",
            "",
            "| order | molecule | family | IC50 nM | Kd M | case call | poses | A/A consensus | single-baseline A | plausible | top model consensus | top 8X6B metrics | top 9E6Y metrics |",
            "| ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in rows:
        m8 = (
            f"{row['top_8x6b_class']}; hotspot={row['top_8x6b_hotspot']}; "
            f"total={row['top_8x6b_total_occlusion']}; cdr3={row['top_8x6b_cdr3_occlusion']}; "
            f"frac={row['top_8x6b_cdr3_fraction']}"
        )
        m9 = (
            f"{row['top_9e6y_class']}; hotspot={row['top_9e6y_hotspot']}; "
            f"total={row['top_9e6y_total_occlusion']}; cdr3={row['top_9e6y_cdr3_occlusion']}; "
            f"frac={row['top_9e6y_cdr3_fraction']}"
        )
        lines.append(
            "| {recommended_order} | {molecule_name} | {family} | {blocking_ic50_nm} | {kd_m} | "
            "{case_level_call} | {pose_count} | {consensus_blocker_like_a} | "
            "{single_baseline_blocker_recheck} | {blocker_plausible_b} | "
            "{top_model_consensus_class} | {m8} | {m9} |".format(**row, m8=m8, m9=m9)
        )

    lines.extend(
        [
            "",
            "## Judgment rule used",
            "",
            "- A-level VHH docking screen: hotspot_overlap_count >= 14, total VHH-PVRL2 residue-pair occlusion >= 500, CDR3-PVRL2 residue-pair occlusion >= 100, CDR3 occlusion fraction >= 0.15.",
            "- Hotspot-only poses with weak PVRL2 occlusion are downgraded instead of treated as blockers.",
            "- 8X6B and 9E6Y are treated as independent baselines; two-baseline support is stronger than one-baseline support.",
            "- Binding/Kd, blocking/IC50, docking geometry, format context, NK/Fc/CD226/TIGIT biology, and positive-control leakage remain separate fields.",
            "",
            "## Reproducibility",
            "",
            "```bash",
            "python docking/success_case_validation/check_patent_success_calibration_status.py",
            "python docking/success_case_validation/summarize_patent_success_calibration.py",
            "python docking/success_case_validation/test_success_case_workflow.py",
            "python docking/success_case_validation/validate_success_case_standards.py",
            "```",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    batch_root = args.batch_root.resolve()
    out_csv = args.out_csv or batch_root / "batch_consensus_summary.csv"
    out_md = args.out_md or batch_root / "PATENT_SUCCESS_SERIES_POSTPROCESS_SUMMARY.md"
    rows = build_rows(batch_root)
    write_csv(out_csv, rows)
    write_md(out_md, rows)
    calls = Counter(row["case_level_call"] for row in rows)
    print("OK patent success calibration summarized")
    print(f"cases={len(rows)}")
    for key, value in sorted(calls.items()):
        print(f"{key}={value}")
    print(f"summary_csv={out_csv}")
    print(f"summary_md={out_md}")


if __name__ == "__main__":
    main()
