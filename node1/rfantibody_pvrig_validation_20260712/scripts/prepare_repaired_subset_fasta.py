#!/usr/bin/env python3
"""Create a repaired-sequence FASTA for candidates listed in a shortlist TSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def prepare(shortlist_tsv: Path, repair_mapping_tsv: Path, output_fasta: Path, audit_json: Path) -> dict[str, object]:
    shortlist = read_tsv(shortlist_tsv)
    mappings = read_tsv(repair_mapping_tsv)
    if not shortlist:
        raise ValueError("shortlist is empty")
    repaired_by_id = {row["candidate_id"]: row["qc_synthesis_sequence"] for row in mappings}
    if len(repaired_by_id) != len(mappings):
        raise ValueError("duplicate candidate ID in repair mapping")
    seen_ids: set[str] = set()
    seen_sequences: set[str] = set()
    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    with output_fasta.open("w", encoding="ascii", newline="\n") as handle:
        for row in shortlist:
            candidate_id = row["candidate_id"]
            if candidate_id in seen_ids:
                raise ValueError(f"duplicate candidate ID in shortlist: {candidate_id}")
            seen_ids.add(candidate_id)
            sequence = repaired_by_id.get(candidate_id)
            if sequence is None:
                raise ValueError(f"candidate missing from repair mapping: {candidate_id}")
            if sequence in seen_sequences:
                raise ValueError(f"duplicate repaired sequence in shortlist: {candidate_id}")
            seen_sequences.add(sequence)
            handle.write(f">{candidate_id}\n{sequence}\n")
    audit: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shortlist_tsv": str(shortlist_tsv.resolve()),
        "shortlist_tsv_sha256": sha256_file(shortlist_tsv),
        "repair_mapping_tsv": str(repair_mapping_tsv.resolve()),
        "repair_mapping_tsv_sha256": sha256_file(repair_mapping_tsv),
        "output_fasta": str(output_fasta.resolve()),
        "output_fasta_sha256": sha256_file(output_fasta),
        "record_count": len(shortlist),
        "unique_sequences": len(seen_sequences),
        "all_checks_passed": True,
    }
    audit_json.parent.mkdir(parents=True, exist_ok=True)
    audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shortlist_tsv", type=Path)
    parser.add_argument("repair_mapping_tsv", type=Path)
    parser.add_argument("output_fasta", type=Path)
    parser.add_argument("audit_json", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.shortlist_tsv, args.repair_mapping_tsv, args.output_fasta, args.audit_json), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

