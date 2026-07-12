#!/usr/bin/env python3
"""Restore the terminal FR4 serine omitted by the RFantibody h-NbBCII10 PDB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


TRUNCATED_SUFFIX = "WGQGTLVTVS"
RESTORED_SUFFIX = "WGQGTLVTVSS"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    current_id: str | None = None
    parts: list[str] = []
    for raw_line in path.read_text(encoding="ascii").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_id is not None:
                records.append((current_id, "".join(parts)))
            current_id = line[1:].split()[0]
            parts = []
        else:
            parts.append(line.upper())
    if current_id is not None:
        records.append((current_id, "".join(parts)))
    return records


def repair(input_fasta: Path, output_fasta: Path, mapping_tsv: Path, audit_json: Path) -> dict[str, object]:
    records = read_fasta(input_fasta)
    if not records:
        raise ValueError("input FASTA has no records")
    ids: set[str] = set()
    output_sequences: set[str] = set()
    mapping: list[dict[str, object]] = []
    output_records: list[tuple[str, str]] = []

    for candidate_id, sequence in records:
        if candidate_id in ids:
            raise ValueError(f"duplicate candidate ID: {candidate_id}")
        ids.add(candidate_id)
        if sequence.endswith(RESTORED_SUFFIX):
            repaired = sequence
            action = "ALREADY_COMPLETE"
        elif sequence.endswith(TRUNCATED_SUFFIX):
            repaired = sequence + "S"
            action = "APPEND_TERMINAL_S"
        else:
            raise ValueError(
                f"{candidate_id}: FR4 suffix is neither {TRUNCATED_SUFFIX!r} nor {RESTORED_SUFFIX!r}"
            )
        if repaired in output_sequences:
            raise ValueError(f"terminal repair creates an exact duplicate: {candidate_id}")
        output_sequences.add(repaired)
        output_records.append((candidate_id, repaired))
        mapping.append(
            {
                "candidate_id": candidate_id,
                "original_sequence": sequence,
                "qc_synthesis_sequence": repaired,
                "action": action,
                "original_length": len(sequence),
                "repaired_length": len(repaired),
            }
        )

    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    temporary_fasta = output_fasta.with_suffix(output_fasta.suffix + ".tmp")
    with temporary_fasta.open("w", encoding="ascii", newline="\n") as handle:
        for candidate_id, sequence in output_records:
            handle.write(f">{candidate_id}\n{sequence}\n")
    os.replace(temporary_fasta, output_fasta)

    mapping_tsv.parent.mkdir(parents=True, exist_ok=True)
    temporary_mapping = mapping_tsv.with_suffix(mapping_tsv.suffix + ".tmp")
    with temporary_mapping.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mapping[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(mapping)
    os.replace(temporary_mapping, mapping_tsv)

    actions: dict[str, int] = {}
    for row in mapping:
        actions[str(row["action"])] = actions.get(str(row["action"]), 0) + 1
    audit: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_fasta": str(input_fasta.resolve()),
        "input_fasta_sha256": sha256_file(input_fasta),
        "output_fasta": str(output_fasta.resolve()),
        "output_fasta_sha256": sha256_file(output_fasta),
        "mapping_tsv": str(mapping_tsv.resolve()),
        "mapping_tsv_sha256": sha256_file(mapping_tsv),
        "record_count": len(mapping),
        "unique_output_sequences": len(output_sequences),
        "actions": actions,
        "reason": (
            "The official RFantibody h-NbBCII10 structural template ends WGQGTLVTVS. "
            "The local VHH L1 gate requires the complete FR4 ending WGQGTLVTVSS."
        ),
        "pose_boundary": (
            "RFantibody design-pose PDBs remain unchanged and omit this terminal residue; "
            "the restored sequence is for sequence QC, synthesis planning, and de novo monomer modeling."
        ),
        "all_checks_passed": True,
    }
    audit_json.parent.mkdir(parents=True, exist_ok=True)
    audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_fasta", type=Path)
    parser.add_argument("output_fasta", type=Path)
    parser.add_argument("mapping_tsv", type=Path)
    parser.add_argument("audit_json", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            repair(args.input_fasta, args.output_fasta, args.mapping_tsv, args.audit_json),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

