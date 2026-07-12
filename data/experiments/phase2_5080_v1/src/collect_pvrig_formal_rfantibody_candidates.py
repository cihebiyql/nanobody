#!/usr/bin/env python3
"""Collect RFantibody PDB outputs into provenance-rich raw and deduplicated candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_TASKS = EXP_DIR / "runs/pvrig_teacher_formal_v1/rfantibody_generation_package/manifests/tasks.tsv"
DEFAULT_PARENTS = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/parent40_manifest.tsv"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates"
SEQUENCE_PDB_RE = re.compile(r"design_(\d+)_dldesign_(\d+)\.pdb$")
CLAIM_BOUNDARY = "generated_pvrig_conditioned_sequences_not_binding_docking_or_blocking_truth"

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
    frame.to_csv(temp_path, index=False)
    temp_path.replace(path)


def write_fasta(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['vhh_sequence']}\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def pdb_chain_sequence(path: Path, chain_id: str) -> str:
    residues: list[str] = []
    seen: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("ATOM") or len(line) < 27 or line[21].strip() != chain_id:
                continue
            key = (line[22:26], line[26:27])
            if key in seen:
                continue
            seen.add(key)
            residue = line[17:20].strip().upper()
            if residue not in AA3_TO_1:
                raise ValueError(f"Unsupported residue {residue!r} in {path} chain {chain_id}")
            residues.append(AA3_TO_1[residue])
    if not residues:
        raise ValueError(f"No residues found in {path} chain {chain_id}")
    return "".join(residues)


def extract_candidate_cdrs(sequence: str, parent: Mapping[str, Any]) -> dict[str, Any]:
    cdr1_start = int(parent["cdr1_start_1based"]) - 1
    cdr1_end = int(parent["cdr1_end_1based"])
    cdr2_start = int(parent["cdr2_start_1based"]) - 1
    cdr2_end = int(parent["cdr2_end_1based"])
    cdr3_start = int(parent["cdr3_start_1based"]) - 1
    fr4 = str(parent["fr4_tail"])
    fr4_start = sequence.find(fr4, cdr3_start + 1)
    if fr4_start < 0:
        raise ValueError(f"Candidate lacks frozen FR4 tail {fr4!r}")
    if sequence[cdr2_start:cdr2_end] != str(parent["cdr2"]):
        raise ValueError("Candidate changed CDR2 outside the registered H1/H3 design modes")
    return {
        "cdr1": sequence[cdr1_start:cdr1_end],
        "cdr1_start_1based": cdr1_start + 1,
        "cdr1_end_1based": cdr1_end,
        "cdr2": sequence[cdr2_start:cdr2_end],
        "cdr2_start_1based": cdr2_start + 1,
        "cdr2_end_1based": cdr2_end,
        "cdr3": sequence[cdr3_start:fr4_start],
        "cdr3_start_1based": cdr3_start + 1,
        "cdr3_end_1based": fr4_start,
        "cdr3_length": fr4_start - cdr3_start,
        "fr4_start_1based": fr4_start + 1,
    }


def validate_framework(sequence: str, parent: Mapping[str, Any], designed_regions: set[str]) -> None:
    parent_sequence = str(parent["sequence"])
    cdr1_start = int(parent["cdr1_start_1based"]) - 1
    cdr1_end = int(parent["cdr1_end_1based"])
    cdr3_start = int(parent["cdr3_start_1based"]) - 1
    parent_fr4_start = parent_sequence.find(str(parent["fr4_tail"]), cdr3_start)
    candidate_fr4_start = sequence.find(str(parent["fr4_tail"]), cdr3_start)
    if parent_fr4_start < 0 or candidate_fr4_start < 0:
        raise ValueError("Unable to anchor FR4 for framework validation")
    protected = [(0, cdr1_start), (cdr1_end, cdr3_start)]
    if "H1" not in designed_regions:
        protected.append((cdr1_start, cdr1_end))
    for start, end in protected:
        if sequence[start:end] != parent_sequence[start:end]:
            raise ValueError(f"Candidate changed protected framework interval {start}:{end}")
    if sequence[candidate_fr4_start:] != parent_sequence[parent_fr4_start:]:
        raise ValueError("Candidate changed protected FR4 suffix")


def collect(
    production_root: Path,
    tasks_path: Path,
    parents_path: Path,
    output_dir: Path,
    allow_incomplete: bool,
) -> dict[str, Any]:
    tasks = pd.read_csv(tasks_path, sep="\t")
    parents = pd.read_csv(parents_path, sep="\t")
    parent_by_id = {str(row["parent_id"]): row for row in parents.to_dict("records")}
    expected_tasks = set(tasks["task_id"].astype(str))
    rows = []
    errors = []
    incomplete_tasks = []
    complete_tasks = []
    for task in tasks.to_dict("records"):
        task_id = str(task["task_id"])
        task_dir = production_root / "tasks" / task_id
        complete_path = task_dir / "status" / "complete.json"
        if not complete_path.is_file():
            incomplete_tasks.append(task_id)
            continue
        complete = json.loads(complete_path.read_text(encoding="utf-8"))
        complete_tasks.append(task_id)
        parent = parent_by_id[str(task["parent_id"])]
        designed_regions = set(str(task["mpnn_loops"]).split(","))
        sequence_files = sorted((task_dir / "sequences").glob("design_*_dldesign_*.pdb"))
        if len(sequence_files) != int(task["expected_raw_records"]):
            errors.append(
                {
                    "task_id": task_id,
                    "error": "sequence_file_count_mismatch",
                    "expected": int(task["expected_raw_records"]),
                    "observed": len(sequence_files),
                }
            )
            continue
        for pdb_path in sequence_files:
            match = SEQUENCE_PDB_RE.search(pdb_path.name)
            if not match:
                errors.append({"task_id": task_id, "path": str(pdb_path), "error": "unparsed_filename"})
                continue
            backbone_index, mpnn_index = map(int, match.groups())
            try:
                sequence = pdb_chain_sequence(pdb_path, "H")
                cdrs = extract_candidate_cdrs(sequence, parent)
                validate_framework(sequence, parent, designed_regions)
            except ValueError as exc:
                errors.append({"task_id": task_id, "path": str(pdb_path), "error": str(exc)})
                continue
            candidate_id = f"RFV1__{task_id}__B{backbone_index:02d}__M{mpnn_index:02d}"
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "vhh_sequence": sequence,
                    "sequence_sha256": sha256_text(sequence),
                    "sequence_length": len(sequence),
                    "parent_id": str(task["parent_id"]),
                    "parent_sequence": str(parent["sequence"]),
                    "parent_sequence_sha256": str(parent["sequence_sha256"]),
                    "parent_framework_cluster": str(task["parent_framework_cluster"]),
                    "formal_split": str(task["formal_split"]),
                    "design_type": "PVRIG_conditioned_CDR_redesign",
                    "design_method": "RFantibody_RFdiffusion_ProteinMPNN",
                    "design_task_id": task_id,
                    "design_mode": str(task["design_mode"]),
                    "designed_regions": str(task["mpnn_loops"]),
                    "design_loops": str(task["design_loops"]),
                    "target_patch_id": str(task["patch_id"]),
                    "hotspots_pdb": str(task["hotspots_pdb"]),
                    "hotspots_uniprot": str(task["hotspots_uniprot"]),
                    "backbone_index": backbone_index,
                    "mpnn_index": mpnn_index,
                    "cdr1_before": str(parent["cdr1"]),
                    "cdr2_before": str(parent["cdr2"]),
                    "cdr3_before": str(parent["cdr3"]),
                    "cdr1_after": cdrs["cdr1"],
                    "cdr2_after": cdrs["cdr2"],
                    "cdr3_after": cdrs["cdr3"],
                    "cdr1_start_1based": cdrs["cdr1_start_1based"],
                    "cdr1_end_1based": cdrs["cdr1_end_1based"],
                    "cdr2_start_1based": cdrs["cdr2_start_1based"],
                    "cdr2_end_1based": cdrs["cdr2_end_1based"],
                    "cdr3_start_1based": cdrs["cdr3_start_1based"],
                    "cdr3_end_1based": cdrs["cdr3_end_1based"],
                    "cdr3_length": cdrs["cdr3_length"],
                    "source_pdb": str(pdb_path),
                    "source_pdb_sha256": sha256_file(pdb_path),
                    "generator_return_code": int(complete["return_code"]),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
    if not allow_incomplete and incomplete_tasks:
        raise RuntimeError(f"Generation is incomplete: {len(incomplete_tasks)} tasks remain")
    if errors:
        raise RuntimeError(json.dumps({"errors": errors[:50], "error_count": len(errors)}, indent=2))
    raw = pd.DataFrame(rows).sort_values("candidate_id").reset_index(drop=True)
    if raw.empty:
        raise RuntimeError("No generated candidates were collected")
    dedup_rows = []
    for _, group in raw.groupby("sequence_sha256", sort=True):
        representative = group.sort_values("candidate_id").iloc[0].to_dict()
        representative["raw_record_count"] = len(group)
        representative["raw_candidate_ids"] = ";".join(sorted(group["candidate_id"].astype(str)))
        representative["source_task_count"] = group["design_task_id"].nunique()
        dedup_rows.append(representative)
    dedup = pd.DataFrame(dedup_rows).sort_values("candidate_id").reset_index(drop=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = output_dir / "rfantibody_candidates_raw_v1.csv"
    dedup_csv = output_dir / "rfantibody_candidates_exact_dedup_v1.csv"
    raw_fasta = output_dir / "rfantibody_candidates_raw_v1.fasta"
    dedup_fasta = output_dir / "rfantibody_candidates_exact_dedup_v1.fasta"
    write_frame_atomic(raw, raw_csv)
    write_frame_atomic(dedup, dedup_csv)
    write_fasta(raw.to_dict("records"), raw_fasta)
    write_fasta(dedup.to_dict("records"), dedup_fasta)
    status = "PASS_COMPLETE_COLLECTION" if not incomplete_tasks else "PASS_PARTIAL_COLLECTION"
    audit: dict[str, Any] = {
        "status": status,
        "schema_version": "pvrig_formal_rfantibody_candidate_collection_audit_v1",
        "production_root": str(production_root),
        "expected_task_count": len(expected_tasks),
        "complete_task_count": len(complete_tasks),
        "incomplete_task_count": len(incomplete_tasks),
        "incomplete_tasks": incomplete_tasks,
        "expected_raw_records_if_complete": int(tasks["expected_raw_records"].sum()),
        "raw_record_count": len(raw),
        "unique_sequence_count": len(dedup),
        "exact_duplicate_record_count": len(raw) - len(dedup),
        "counts_by_patch": dict(Counter(raw["target_patch_id"].astype(str))),
        "counts_by_mode": dict(Counter(raw["design_mode"].astype(str))),
        "counts_by_formal_split": dict(Counter(raw["formal_split"].astype(str))),
        "parent_count": raw["parent_id"].nunique(),
        "output_paths": {
            "raw_csv": str(raw_csv), "dedup_csv": str(dedup_csv),
            "raw_fasta": str(raw_fasta), "dedup_fasta": str(dedup_fasta),
        },
        "output_sha256": {
            "raw_csv": sha256_file(raw_csv), "dedup_csv": sha256_file(dedup_csv),
            "raw_fasta": sha256_file(raw_fasta), "dedup_fasta": sha256_file(dedup_fasta),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (output_dir / "collection_audit_v1.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--parents", type=Path, default=DEFAULT_PARENTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-incomplete", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            collect(args.production_root, args.tasks, args.parents, args.output_dir, args.allow_incomplete),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
