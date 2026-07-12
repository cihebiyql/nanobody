#!/usr/bin/env python3
"""Prepare sequence inputs for the pilot96 ESM2 cache and V3-P1 smoke."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_manifest.tsv"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_OUTDIR = EXP_DIR / "prepared/pvrig_teacher_pilot96/model_inputs"
CLAIM_BOUNDARY = "sequence_inputs_for_single_framework_v3_p1_pipeline_smoke"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_target(path: Path) -> str:
    sequence = "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )
    if not sequence:
        raise ValueError(f"Empty target FASTA: {path}")
    return sequence


def run(selection: Path, target_fasta: Path, outdir: Path) -> dict[str, object]:
    with selection.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != 96 or len({row["candidate_id"] for row in rows}) != 96:
        raise ValueError("The pilot selection must contain 96 unique candidates")
    target = read_target(target_fasta)
    outdir.mkdir(parents=True, exist_ok=True)
    candidate_path = outdir / "pvrig_teacher_pilot96_candidates.csv"
    pair_path = outdir / "pvrig_teacher_pilot96_pair_inputs.csv"

    with candidate_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["candidate_id", "vhh_seq", "cdr1", "cdr2", "cdr3", "parent_framework_cluster", "hotspot_set"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "candidate_id": row["candidate_id"],
                    "vhh_seq": row["sequence"],
                    "cdr1": row["cdr1"],
                    "cdr2": row["cdr2"],
                    "cdr3": row["cdr3"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                    "hotspot_set": row["hotspot_set"],
                }
            )

    with pair_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["sample_id", "vhh_sequence", "target_id", "target_sequence", "teacher_split", "claim_boundary"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "sample_id": row["candidate_id"],
                    "vhh_sequence": row["sequence"],
                    "target_id": "PVRIG_structural_ectodomain_proxy_v1",
                    "target_sequence": target,
                    "teacher_split": "pilot_only",
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )

    audit: dict[str, object] = {
        "status": "PASS",
        "schema_version": "pvrig_teacher_pilot96_model_inputs_v1",
        "records": len(rows),
        "unique_vhh_sequences": len({row["sequence"] for row in rows}),
        "target_length": len(target),
        "parent_framework_clusters": sorted({row["parent_framework_cluster"] for row in rows}),
        "candidate_csv": str(candidate_path),
        "pair_csv": str(pair_path),
        "sha256": {
            "selection": sha256_file(selection),
            "target_fasta": sha256_file(target_fasta),
            "candidate_csv": sha256_file(candidate_path),
            "pair_csv": sha256_file(pair_path),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (outdir / "prepare_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.selection, args.target_fasta, args.outdir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
