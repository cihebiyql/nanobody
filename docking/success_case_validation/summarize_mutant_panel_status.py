#!/usr/bin/env python3
"""Summarize structure/docking/postprocess status for the mutant validation panel."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_ROOT = ROOT / "docking" / "calibration" / "mutant_validation_panel"
FIELDS = [
    "panel_order",
    "mutant_name",
    "base_molecule",
    "mutation_class",
    "mutations_1based",
    "monomer_raw_pdb",
    "monomer_chainA_pdb",
    "structure_qc_sane",
    "haddock_run_dir",
    "classification_8x6b_csv",
    "classification_9e6y_csv",
    "consensus_csv",
    "consensus_rows",
    "consensus_blocker_like_a",
    "single_baseline_blocker_recheck",
    "blocker_plausible_b",
    "evidence_inference_only_e",
    "workdir",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, default=DEFAULT_PANEL_ROOT)
    parser.add_argument("--panel-csv", type=Path)
    parser.add_argument("--out-csv", type=Path)
    parser.add_argument("--out-md", type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def exists_text(path: Path) -> str:
    return "yes" if path.exists() else "no"


def qc_sane(path: Path) -> str:
    if not path.exists():
        return "missing"
    data = json.loads(path.read_text(encoding="utf-8"))
    chain_a = data.get("chains", {}).get("A", {})
    return "yes" if chain_a.get("likely_sane_backbone") is True else "no"


def consensus_counts(path: Path) -> Counter[str]:
    if not path.exists():
        return Counter()
    return Counter(row.get("consensus_class", "") for row in read_csv(path))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_md(path: Path, rows: list[dict[str, str]]) -> None:
    structure_done = sum(1 for row in rows if row["monomer_chainA_pdb"] == "yes")
    docking_done = sum(1 for row in rows if row["haddock_run_dir"] == "yes")
    consensus_done = sum(1 for row in rows if row["consensus_csv"] == "yes")
    aggregate = Counter()
    for row in rows:
        aggregate["CONSENSUS_BLOCKER_LIKE_A"] += int(row["consensus_blocker_like_a"])
        aggregate["SINGLE_BASELINE_BLOCKER_RECHECK"] += int(row["single_baseline_blocker_recheck"])
        aggregate["BLOCKER_PLAUSIBLE_B"] += int(row["blocker_plausible_b"])
        aggregate["EVIDENCE_INFERENCE_ONLY_E"] += int(row["evidence_inference_only_e"])
    lines = [
        "# Mutant Panel Status Summary",
        "",
        "## Bottom line",
        "",
        f"- Panel records: {len(rows)}",
        f"- Structure-ready records: {structure_done}",
        f"- HADDOCK run dirs present: {docking_done}",
        f"- Consensus postprocessed records: {consensus_done}",
        f"- Consensus aggregate: A/A={aggregate['CONSENSUS_BLOCKER_LIKE_A']}; single-A={aggregate['SINGLE_BASELINE_BLOCKER_RECHECK']}; B={aggregate['BLOCKER_PLAUSIBLE_B']}; E={aggregate['EVIDENCE_INFERENCE_ONLY_E']}",
        "",
        "## Completed rows",
        "",
        "| mutant | mutation | structure | docking | consensus rows | A/A | single-A | B | E |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        if row["monomer_chainA_pdb"] == "yes" or row["haddock_run_dir"] == "yes" or row["consensus_csv"] == "yes":
            lines.append(
                f"| {row['mutant_name']} | {row['mutations_1based']} | {row['monomer_chainA_pdb']} | "
                f"{row['haddock_run_dir']} | {row['consensus_rows']} | {row['consensus_blocker_like_a']} | "
                f"{row['single_baseline_blocker_recheck']} | {row['blocker_plausible_b']} | {row['evidence_inference_only_e']} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- This status summary records computational workflow completion only.",
            "- Mutant rows derived from known positives remain validation/leakage controls unless explicitly promoted after separate novelty review.",
            "- Single-baseline A rows still require redock/manual inspection before final blocker prioritization.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    panel_root = args.panel_root.resolve()
    panel_csv = args.panel_csv or panel_root / "mutant_panel.csv"
    rows_in = read_csv(panel_csv)
    rows: list[dict[str, str]] = []
    for item in rows_in:
        workdir = Path(item["workdir"]) if item.get("workdir") else panel_root / "workdirs" / item["mutant_name"]
        name = item["mutant_name"]
        consensus = workdir / "reports" / f"{name}_8x6b_9e6y_consensus.csv"
        counts = consensus_counts(consensus)
        rows.append(
            {
                "panel_order": item["panel_order"],
                "mutant_name": name,
                "base_molecule": item["base_molecule"],
                "mutation_class": item["mutation_class"],
                "mutations_1based": item["mutations_1based"],
                "monomer_raw_pdb": exists_text(workdir / "monomer" / f"{name}_nanobodybuilder2.pdb"),
                "monomer_chainA_pdb": exists_text(workdir / "haddock3" / "data" / f"{name}_vhh_chainA.pdb"),
                "structure_qc_sane": qc_sane(workdir / "reports" / "structure_qc_chainA.json"),
                "haddock_run_dir": exists_text(workdir / "haddock3" / f"run_{name}_pvrig_hotspot_test"),
                "classification_8x6b_csv": exists_text(workdir / "reports" / f"{name}_8x6b_blocker_classification.csv"),
                "classification_9e6y_csv": exists_text(workdir / "reports" / f"{name}_9e6y_blocker_classification.csv"),
                "consensus_csv": exists_text(consensus),
                "consensus_rows": str(sum(counts.values())),
                "consensus_blocker_like_a": str(counts["CONSENSUS_BLOCKER_LIKE_A"]),
                "single_baseline_blocker_recheck": str(counts["SINGLE_BASELINE_BLOCKER_RECHECK"]),
                "blocker_plausible_b": str(counts["BLOCKER_PLAUSIBLE_B"]),
                "evidence_inference_only_e": str(counts["EVIDENCE_INFERENCE_ONLY_E"]),
                "workdir": str(workdir),
            }
        )
    out_csv = args.out_csv or panel_root / "mutant_panel_status.csv"
    out_md = args.out_md or panel_root / "MUTANT_PANEL_STATUS_SUMMARY.md"
    write_csv(out_csv, rows)
    write_md(out_md, rows)
    print("OK mutant panel status summarized")
    print(f"records={len(rows)}")
    print(f"structure_ready={sum(1 for row in rows if row['monomer_chainA_pdb'] == 'yes')}")
    print(f"haddock_run_dirs={sum(1 for row in rows if row['haddock_run_dir'] == 'yes')}")
    print(f"consensus_csv={sum(1 for row in rows if row['consensus_csv'] == 'yes')}")
    print(f"out_csv={out_csv}")
    print(f"out_md={out_md}")


if __name__ == "__main__":
    main()
