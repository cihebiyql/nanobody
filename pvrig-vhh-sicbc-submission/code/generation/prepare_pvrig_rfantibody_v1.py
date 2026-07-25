#!/usr/bin/env python3
"""Complete the RFantibody example framework FR4 and freeze candidate provenance.

The RFantibody PDB-derived sequences end in ``...VTVS`` because the example
structure lacks the terminal serine expected by the local full-length VHH
gate. This script does not overwrite generation outputs. It creates a v1
derived library with one terminal ``S`` appended and clean FASTA identifiers.
"""
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
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_SOURCE = WORKSPACE_ROOT / "node1/rfantibody_pvrig_1000/results/final/pvrig_rfantibody_1000.tsv"
DEFAULT_OUTDIR = EXP_DIR / "prepared/pvrig_rfantibody_v1"
CLAIM_BOUNDARY = "generated_candidate_library_not_binding_or_blocker_proof"

FIELDS = [
    "candidate_id",
    "source_candidate_id",
    "source_sequence",
    "source_sequence_sha256",
    "sequence",
    "sequence_sha256",
    "sequence_repair",
    "source_sequence_length",
    "sequence_length",
    "hotspot_set",
    "hotspots_pdb",
    "hotspots_uniprot",
    "framework_id",
    "parent_framework_cluster",
    "backbone_index",
    "mpnn_index",
    "cdr1",
    "cdr2",
    "cdr3",
    "rfd_mindist",
    "rfd_averagemin",
    "rfd_hotspot_distance_bin",
    "rfd_final_plddt_mean",
    "source_backbone_pdb",
    "source_backbone_trb",
    "source_mpnn_pdb",
    "formal_split",
    "calibration_only",
    "submission_eligible",
    "claim_boundary",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def repaired_id(source_id: str) -> str:
    if "_v0_" not in source_id:
        raise ValueError(f"Unexpected source candidate id: {source_id}")
    return source_id.replace("_v0_", "_v1_", 1)


def repair_row(source: dict[str, str]) -> dict[str, str]:
    source_id = clean(source.get("candidate_id"))
    sequence = clean(source.get("sequence")).upper()
    expected_hash = clean(source.get("sequence_sha256"))
    if not source_id or not sequence:
        raise ValueError("Missing candidate_id or sequence")
    if sha256_text(sequence) != expected_hash:
        raise ValueError(f"Source sequence hash mismatch: {source_id}")
    if not sequence.endswith("VTVS") or sequence.endswith("VTVSS"):
        raise ValueError(f"Source sequence does not have the expected truncated FR4: {source_id}")
    repaired = sequence + "S"
    return {
        "candidate_id": repaired_id(source_id),
        "source_candidate_id": source_id,
        "source_sequence": sequence,
        "source_sequence_sha256": expected_hash,
        "sequence": repaired,
        "sequence_sha256": sha256_text(repaired),
        "sequence_repair": "append_terminal_S_to_restore_FR4_TVSS",
        "source_sequence_length": str(len(sequence)),
        "sequence_length": str(len(repaired)),
        "hotspot_set": clean(source.get("hotspot_set")),
        "hotspots_pdb": clean(source.get("hotspots_pdb")),
        "hotspots_uniprot": clean(source.get("hotspots_uniprot")),
        "framework_id": clean(source.get("framework_id")),
        "parent_framework_cluster": clean(source.get("framework_id")),
        "backbone_index": clean(source.get("backbone_index")),
        "mpnn_index": clean(source.get("mpnn_index")),
        "cdr1": clean(source.get("cdr1")),
        "cdr2": clean(source.get("cdr2")),
        "cdr3": clean(source.get("cdr3")),
        "rfd_mindist": clean(source.get("rfd_mindist")),
        "rfd_averagemin": clean(source.get("rfd_averagemin")),
        "rfd_hotspot_distance_bin": clean(source.get("rfd_hotspot_distance_bin")),
        "rfd_final_plddt_mean": clean(source.get("rfd_final_plddt_mean")),
        "source_backbone_pdb": clean(source.get("backbone_pdb")),
        "source_backbone_trb": clean(source.get("backbone_trb")),
        "source_mpnn_pdb": clean(source.get("mpnn_pdb")),
        "formal_split": "pilot_only_no_formal_parent_holdout_single_framework",
        "calibration_only": "false",
        "submission_eligible": "pending_full_qc_and_geometry",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def run(source_path: Path, outdir: Path) -> dict[str, object]:
    with source_path.open(newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle, delimiter="\t"))
    rows = [repair_row(source) for source in source_rows]
    if len(rows) != 1000:
        raise ValueError(f"Expected 1000 source rows, found {len(rows)}")
    ids = [row["candidate_id"] for row in rows]
    sequences = [row["sequence"] for row in rows]
    if len(set(ids)) != len(ids) or len(set(sequences)) != len(sequences):
        raise ValueError("Derived IDs or sequences are not exact-unique")
    if {row["framework_id"] for row in rows} != {"h-NbBCII10"}:
        raise ValueError("Unexpected framework inventory")

    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "candidate_manifest.tsv"
    fasta_path = outdir / "pvrig_rfantibody_1000_fr4_complete.fasta"
    summary_path = outdir / "repair_summary.json"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    with fasta_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    hotspot_counts: dict[str, int] = {}
    for row in rows:
        hotspot_counts[row["hotspot_set"]] = hotspot_counts.get(row["hotspot_set"], 0) + 1
    summary: dict[str, object] = {
        "status": "PASS",
        "schema_version": "pvrig_rfantibody_candidate_library_v1",
        "source": str(source_path),
        "source_sha256": sha256_file(source_path),
        "records": len(rows),
        "exact_unique_ids": len(set(ids)),
        "exact_unique_sequences": len(set(sequences)),
        "source_length_range": [min(len(row["source_sequence"]) for row in rows), max(len(row["source_sequence"]) for row in rows)],
        "derived_length_range": [min(len(row["sequence"]) for row in rows), max(len(row["sequence"]) for row in rows)],
        "terminal_tvss_count": sum(row["sequence"].endswith("TVSS") for row in rows),
        "hotspot_counts": dict(sorted(hotspot_counts.items())),
        "frameworks": sorted({row["framework_id"] for row in rows}),
        "formal_split_status": "NOT_AVAILABLE_SINGLE_FRAMEWORK_PILOT_ONLY",
        "manifest_sha256": sha256_file(manifest_path),
        "fasta_sha256": sha256_file(fasta_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.source, args.outdir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
