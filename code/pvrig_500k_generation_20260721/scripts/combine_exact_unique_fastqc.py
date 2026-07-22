#!/usr/bin/env python3
"""Combine exact-unique fast-QC tables while preserving provenance and hashes."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tsv_path = output / "combined_exact_unique_fast_qc_pass.tsv.gz"
    fasta_path = output / "combined_exact_unique_fast_qc_pass.fasta.gz"
    seen_sequences: set[str] = set()
    seen_ids: set[str] = set()
    fields: list[str] = []
    for source in args.input:
        with gzip.open(source, "rt", encoding="utf-8", newline="") as handle:
            source_fields = csv.DictReader(handle, delimiter="\t").fieldnames
        if source_fields is None:
            raise ValueError(f"missing header: {source}")
        for field in source_fields:
            if field not in fields:
                fields.append(field)
    route_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    source_counts: dict[str, int] = {}
    with gzip.open(tsv_path, "wt", encoding="utf-8", newline="", compresslevel=1) as tsv, gzip.open(
        fasta_path, "wt", encoding="utf-8", compresslevel=1
    ) as fasta:
        writer = csv.DictWriter(tsv, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for source in args.input:
            count = 0
            with gzip.open(source, "rt", encoding="utf-8", newline="") as handle:
                rows = csv.DictReader(handle, delimiter="\t")
                if rows.fieldnames is None:
                    raise ValueError(f"missing header: {source}")
                for row in rows:
                    if row["fast_qc_status"] != "PASS" or row.get("exact_duplicate_global") != "false":
                        raise ValueError(f"input is not frozen exact-unique PASS: {row['candidate_id']}")
                    if row["sequence"] in seen_sequences:
                        raise ValueError(f"duplicate sequence across inputs: {row['candidate_id']}")
                    if row["candidate_id"] in seen_ids:
                        raise ValueError(f"duplicate candidate ID across inputs: {row['candidate_id']}")
                    seen_sequences.add(row["sequence"]); seen_ids.add(row["candidate_id"])
                    writer.writerow(row)
                    fasta.write(f">{row['candidate_id']}\n{row['sequence']}\n")
                    route_counts[row["route_id"]] += 1
                    mode_counts[f"{row['route_id']}|{row['design_mode']}"] += 1
                    count += 1
            source_counts[str(source.resolve())] = count
    receipt = {
        "status": "COMBINED_EXACT_UNIQUE_FAST_QC_NOT_FINAL_ANARCI",
        "exact_unique_count": len(seen_sequences),
        "candidate_id_count": len(seen_ids),
        "source_counts": source_counts,
        "route_counts": dict(sorted(route_counts.items())),
        "route_mode_counts": dict(sorted(mode_counts.items())),
        "outputs": {tsv_path.name: sha256_file(tsv_path), fasta_path.name: sha256_file(fasta_path)},
        "note": "ANARCI/IMGT and CDR3-family controls remain required before a final 300k CPU-route freeze.",
    }
    (output / "COMBINE_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
