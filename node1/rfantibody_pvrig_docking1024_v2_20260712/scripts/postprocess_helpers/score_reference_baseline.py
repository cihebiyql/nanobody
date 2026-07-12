#!/usr/bin/env python3
"""Batch-align and score a pose set against one PVRIG:PVRL2 reference baseline."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="Comma-separated model IDs without suffix.")
    parser.add_argument("--pose-dir", required=True, type=Path, help="Input pose directory.")
    parser.add_argument(
        "--pose-pattern",
        default="{model}_aligned_to_8x6b.pdb",
        help="Input file pattern relative to --pose-dir. Use {model}.",
    )
    parser.add_argument("--output-pose-dir", required=True, type=Path, help="Aligned output PDB directory.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output report directory.")
    parser.add_argument("--reference-pdb", required=True, type=Path)
    parser.add_argument("--baseline-label", required=True, help="Short label, e.g. 9e6y.")
    parser.add_argument("--mobile-pvrig-chain", default="B")
    parser.add_argument("--reference-pvrig-chain", required=True)
    parser.add_argument("--vhh-chain", default="A")
    parser.add_argument("--reference-pvrl2-chain", required=True)
    parser.add_argument("--pair-map-csv", required=True, type=Path)
    parser.add_argument("--mobile-ref-column", required=True)
    parser.add_argument("--reference-ref-column", required=True)
    parser.add_argument("--hotspots-csv", required=True, type=Path)
    parser.add_argument("--hotspot-ref-column", required=True)
    parser.add_argument("--cdr1", default="26-35")
    parser.add_argument("--cdr2", default="53-59")
    parser.add_argument("--cdr3", default="98-116")
    parser.add_argument("--rank-score-csv", type=Path, help="Optional CSV with model, haddock_rank, haddock_score.")
    return parser.parse_args()


def read_rank_rows(path: Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {row["model"]: row for row in csv.DictReader(fh)}


def read_one_row_csv(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return next(csv.DictReader(fh))


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True)


def parse_rmsd(align_stdout: str) -> str:
    for line in align_stdout.splitlines():
        if "rmsd=" in line:
            return line.split("rmsd=")[1].split()[0]
    return ""


def summarize_cdr_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    regions = data["regions"]
    cdr1 = regions["CDR1"]
    cdr2 = regions["CDR2"]
    cdr3 = regions["CDR3"]
    framework = regions["framework"]
    total_atoms = data["total_occluding_atom_contact_count"]
    total_pairs = data["total_occluding_residue_pair_count"]
    return {
        "total_vhh_pvrl2_atom_occlusion": total_atoms,
        "total_vhh_pvrl2_residue_pair_occlusion": total_pairs,
        "total_vhh_pvrl2_atom_clash": data["total_clash_atom_contact_count"],
        "total_vhh_pvrl2_residue_pair_clash": data["total_clash_residue_pair_count"],
        "cdr3_atom_occlusion": cdr3["occluding_atom_contact_count"],
        "cdr3_atom_occlusion_fraction": cdr3["occluding_atom_contact_count"] / total_atoms if total_atoms else 0,
        "cdr3_residue_pair_occlusion": cdr3["occluding_residue_pair_count"],
        "cdr3_residue_pair_occlusion_fraction": cdr3["occluding_residue_pair_count"] / total_pairs if total_pairs else 0,
        "cdr3_atom_clash": cdr3["clash_atom_contact_count"],
        "cdr3_residue_pair_clash": cdr3["clash_residue_pair_count"],
        "cdr3_vhh_residue_count": len(cdr3.get("vhh_residues", [])),
        "cdr3_pvrl2_residue_count": len(cdr3.get("pvrl2_residues", [])),
        "cdr12_atom_occlusion": cdr1["occluding_atom_contact_count"] + cdr2["occluding_atom_contact_count"],
        "cdr12_residue_pair_occlusion": cdr1["occluding_residue_pair_count"] + cdr2["occluding_residue_pair_count"],
        "framework_atom_occlusion": framework["occluding_atom_contact_count"],
        "framework_residue_pair_occlusion": framework["occluding_residue_pair_count"],
        "framework_residue_pair_occlusion_fraction": (
            framework["occluding_residue_pair_count"] / total_pairs if total_pairs else 0
        ),
    }


def write_rows(path: Path, rows: list[dict[str, object]], preferred_fields: list[str]) -> None:
    fields = list(preferred_fields)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not models:
        raise SystemExit("No models provided")
    args.output_pose_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "json").mkdir(parents=True, exist_ok=True)
    (args.out_dir / "per_model_scores").mkdir(parents=True, exist_ok=True)
    rank_rows = read_rank_rows(args.rank_score_csv)
    pose_rows: list[dict[str, object]] = []
    cdr_rows: list[dict[str, object]] = []

    for model in models:
        input_pdb = args.pose_dir / args.pose_pattern.format(model=model)
        output_pdb = args.output_pose_dir / f"{model}_aligned_to_{args.baseline_label}.pdb"
        align_stdout = run(
            [
                sys.executable,
                str(SCRIPT_DIR / "align_pdb_by_chain.py"),
                "--mobile-pdb",
                str(input_pdb),
                "--reference-pdb",
                str(args.reference_pdb),
                "--mobile-chain",
                args.mobile_pvrig_chain,
                "--reference-chain",
                args.reference_pvrig_chain,
                "--pair-map-csv",
                str(args.pair_map_csv),
                "--mobile-ref-column",
                args.mobile_ref_column,
                "--reference-ref-column",
                args.reference_ref_column,
                "--out-pdb",
                str(output_pdb),
            ]
        )
        rmsd = parse_rmsd(align_stdout)
        pose_score_csv = args.out_dir / "per_model_scores" / f"{model}_{args.baseline_label}_pose_score.csv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "score_pvrig_vhh_pose.py"),
                "--pose-pdb",
                str(output_pdb),
                "--reference-pdb",
                str(args.reference_pdb),
                "--pvrig-chain",
                args.mobile_pvrig_chain,
                "--vhh-chain",
                args.vhh_chain,
                "--ref-pvrig-chain",
                args.reference_pvrig_chain,
                "--ref-pvrl2-chain",
                args.reference_pvrl2_chain,
                "--hotspots-csv",
                str(args.hotspots_csv),
                "--hotspot-ref-column",
                args.hotspot_ref_column,
                "--assume-aligned",
                "--cdr-ranges",
                f"CDR1:{args.cdr1},CDR2:{args.cdr2},CDR3:{args.cdr3}",
                "--out-csv",
                str(pose_score_csv),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        pose_row: dict[str, object] = read_one_row_csv(pose_score_csv)
        rank_row = rank_rows.get(model, {})
        pose_row.update(
            {
                "model": model,
                "baseline": args.baseline_label,
                "haddock_rank": rank_row.get("haddock_rank", ""),
                "haddock_score": rank_row.get("haddock_score", ""),
                "align_rmsd_A": rmsd,
            }
        )
        pose_rows.append(pose_row)

        cdr_json = args.out_dir / "json" / f"{model}_{args.baseline_label}_cdr_occlusion.json"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "score_cdr_region_occlusion.py"),
                "--pose-pdb",
                str(output_pdb),
                "--reference-pdb",
                str(args.reference_pdb),
                "--vhh-chain",
                args.vhh_chain,
                "--ref-pvrl2-chain",
                args.reference_pvrl2_chain,
                "--cdr1",
                args.cdr1,
                "--cdr2",
                args.cdr2,
                "--cdr3",
                args.cdr3,
                "--out-json",
                str(cdr_json),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        cdr_row = {
            "model": model,
            "baseline": args.baseline_label,
            "haddock_rank": rank_row.get("haddock_rank", ""),
            "haddock_score": rank_row.get("haddock_score", ""),
            "hotspot_overlap_count": pose_row.get("hotspot_overlap_count", ""),
            "align_rmsd_A": rmsd,
        }
        cdr_row.update(summarize_cdr_json(cdr_json))
        cdr_rows.append(cdr_row)

    score_path = args.out_dir / f"haddock3_top_model_mechanism_scores_{args.baseline_label}.csv"
    cdr_path = args.out_dir / f"cdr3_occlusion_summary_{args.baseline_label}.csv"
    write_rows(score_path, pose_rows, ["model", "baseline", "haddock_rank", "haddock_score", "align_rmsd_A"])
    write_rows(cdr_path, cdr_rows, ["model", "baseline", "haddock_rank", "haddock_score", "hotspot_overlap_count", "align_rmsd_A"])
    print(f"wrote {score_path}")
    print(f"wrote {cdr_path}")
    for row in cdr_rows:
        print(
            "{model} rmsd={align_rmsd_A} hotspot={hotspot_overlap_count} total={total} cdr3={cdr3} frac={frac:.3f}".format(
                model=row["model"],
                align_rmsd_A=row["align_rmsd_A"],
                hotspot_overlap_count=row["hotspot_overlap_count"],
                total=row["total_vhh_pvrl2_residue_pair_occlusion"],
                cdr3=row["cdr3_residue_pair_occlusion"],
                frac=float(row["cdr3_residue_pair_occlusion_fraction"]),
            )
        )


if __name__ == "__main__":
    main()
