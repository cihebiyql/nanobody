#!/usr/bin/env python3
"""Freeze an exact candidate-ID set difference with auditable hashes."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_ids(path: Path) -> set[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        ids = [row["candidate_id"] for row in reader]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate candidate_id in exclusion: {path}")
    return set(ids)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source", type=int, required=True)
    parser.add_argument("--expected-exclude", type=int, required=True)
    parser.add_argument("--expected-output", type=int, required=True)
    args = parser.parse_args()

    excluded = read_ids(args.exclude)
    if len(excluded) != args.expected_exclude:
        raise ValueError(f"exclude count {len(excluded)} != {args.expected_exclude}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    table = args.output_dir / "exact_id_difference.tsv.gz"
    fasta = args.output_dir / "exact_id_difference.fasta.gz"
    table_partial = table.with_suffix(table.suffix + ".partial")
    fasta_partial = fasta.with_suffix(fasta.suffix + ".partial")

    seen_ids: set[str] = set()
    seen_sequences: set[str] = set()
    source_count = output_count = overlap_count = 0
    with gzip.open(args.source, "rt", newline="") as source, gzip.open(
        table_partial, "wt", newline=""
    ) as table_handle, gzip.open(fasta_partial, "wt") as fasta_handle:
        reader = csv.DictReader(source, delimiter="\t")
        if not reader.fieldnames or "candidate_id" not in reader.fieldnames or "sequence" not in reader.fieldnames:
            raise ValueError("source must contain candidate_id and sequence")
        writer = csv.DictWriter(table_handle, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in reader:
            source_count += 1
            candidate_id = row["candidate_id"]
            sequence = row["sequence"].strip().upper()
            if candidate_id in seen_ids:
                raise ValueError(f"duplicate source candidate_id: {candidate_id}")
            if sequence in seen_sequences:
                raise ValueError(f"duplicate source sequence: {candidate_id}")
            seen_ids.add(candidate_id)
            seen_sequences.add(sequence)
            if candidate_id in excluded:
                overlap_count += 1
                continue
            writer.writerow(row)
            fasta_handle.write(f">{candidate_id}\n{sequence}\n")
            output_count += 1

    if source_count != args.expected_source:
        raise ValueError(f"source count {source_count} != {args.expected_source}")
    missing = excluded - seen_ids
    if missing:
        raise ValueError(f"exclusion is not a source subset; missing={len(missing)}")
    if overlap_count != args.expected_exclude or output_count != args.expected_output:
        raise ValueError(
            f"count mismatch overlap={overlap_count} output={output_count}"
        )
    os.replace(table_partial, table)
    os.replace(fasta_partial, fasta)
    receipt = {
        "status": "PASS",
        "source_records": source_count,
        "excluded_records": len(excluded),
        "overlap_records": overlap_count,
        "output_records": output_count,
        "id_set_exact_difference": True,
        "sequence_exact_unique": True,
        "source": str(args.source.resolve()),
        "exclude": str(args.exclude.resolve()),
        "outputs": {
            table.name: sha256(table),
            fasta.name: sha256(fasta),
        },
    }
    (args.output_dir / "FREEZE_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    (args.output_dir / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in receipt["outputs"].items())
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
