#!/usr/bin/env python3
"""Freeze first-occurrence exact-unique sequences from a fast-QC PASS table."""

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
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tsv_path = output / "exact_unique_fast_qc_pass.tsv.gz"
    fasta_path = output / "exact_unique_fast_qc_pass.fasta.gz"
    seen: set[str] = set()
    input_count = duplicate_count = 0
    route_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    with gzip.open(source, "rt", encoding="utf-8", newline="") as src, gzip.open(
        tsv_path, "wt", encoding="utf-8", newline="", compresslevel=1
    ) as tsv, gzip.open(fasta_path, "wt", encoding="utf-8", compresslevel=1) as fasta:
        rows = csv.DictReader(src, delimiter="\t")
        if rows.fieldnames is None:
            raise ValueError("input table has no header")
        fields = list(rows.fieldnames)
        if "exact_duplicate_global" not in fields:
            fields.append("exact_duplicate_global")
        writer = csv.DictWriter(tsv, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            input_count += 1
            sequence = row["sequence"]
            if sequence in seen:
                duplicate_count += 1
                continue
            seen.add(sequence)
            row["exact_duplicate_global"] = "false"
            writer.writerow(row)
            fasta.write(f">{row['candidate_id']}\n{sequence}\n")
            route_counts[row["route_id"]] += 1
            mode_counts[f"{row['route_id']}|{row['design_mode']}"] += 1
    receipt = {
        "status": "EXACT_UNIQUE_FAST_QC_FROZEN_NOT_FINAL_ANARCI",
        "input_fast_qc_pass_count": input_count,
        "exact_duplicate_removed_count": duplicate_count,
        "exact_unique_count": len(seen),
        "route_counts": dict(sorted(route_counts.items())),
        "route_mode_counts": dict(sorted(mode_counts.items())),
        "outputs": {
            tsv_path.name: sha256_file(tsv_path),
            fasta_path.name: sha256_file(fasta_path),
        },
        "note": "ANARCI/IMGT and CDR3-family controls remain required.",
    }
    (output / "EXACT_UNIQUE_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
