#!/usr/bin/env python3
"""Validate RFantibody final TSV and emit FASTA headers stable across QC tools."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_COLUMNS = {
    "candidate_id",
    "hotspot_set",
    "backbone_index",
    "mpnn_index",
    "sequence",
    "cdr1",
    "cdr2",
    "cdr3",
    "valid_sequence",
    "exact_known_positive_match",
}
VALID_AA = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
VALID_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_expected_set_counts(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        name, separator, raw_count = value.partition("=")
        if not separator or not name or not raw_count.isdigit():
            raise ValueError(f"Invalid --expected-set-count value: {value!r}")
        result[name] = int(raw_count)
    return result


def is_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def prepare(
    source_tsv: Path,
    output_fasta: Path,
    audit_json: Path,
    *,
    expected_count: int | None,
    expected_set_counts: dict[str, int],
) -> dict[str, object]:
    with source_tsv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required TSV columns: {sorted(missing)}")
        rows = list(reader)

    errors: list[str] = []
    ids: set[str] = set()
    sequences: set[str] = set()
    set_counts: Counter[str] = Counter()
    backbone_keys: set[tuple[str, str]] = set()
    cdr3_lengths: Counter[int] = Counter()

    for line_number, row in enumerate(rows, start=2):
        candidate_id = row["candidate_id"].strip()
        sequence = row["sequence"].strip().upper()
        hotspot_set = row["hotspot_set"].strip()
        if not candidate_id or not VALID_ID.fullmatch(candidate_id):
            errors.append(f"line {line_number}: unstable candidate_id {candidate_id!r}")
        if candidate_id in ids:
            errors.append(f"line {line_number}: duplicate candidate_id {candidate_id!r}")
        ids.add(candidate_id)
        if not sequence or not VALID_AA.fullmatch(sequence):
            errors.append(f"line {line_number}: invalid amino-acid sequence for {candidate_id!r}")
        if sequence in sequences:
            errors.append(f"line {line_number}: duplicate exact sequence for {candidate_id!r}")
        sequences.add(sequence)
        if not is_true(row["valid_sequence"]):
            errors.append(f"line {line_number}: source marks sequence invalid for {candidate_id!r}")
        if is_true(row["exact_known_positive_match"]):
            errors.append(f"line {line_number}: exact known-positive leakage for {candidate_id!r}")
        set_counts[hotspot_set] += 1
        backbone_keys.add((hotspot_set, row["backbone_index"].strip()))
        cdr3_lengths[len(row["cdr3"].strip())] += 1

    if expected_count is not None and len(rows) != expected_count:
        errors.append(f"expected {expected_count} records, found {len(rows)}")
    for name, expected in expected_set_counts.items():
        observed = set_counts.get(name, 0)
        if observed != expected:
            errors.append(f"hotspot set {name}: expected {expected}, found {observed}")
    unexpected_sets = sorted(set(set_counts) - set(expected_set_counts)) if expected_set_counts else []
    if unexpected_sets:
        errors.append(f"unexpected hotspot sets: {unexpected_sets}")
    if errors:
        raise ValueError("RFantibody input validation failed:\n- " + "\n- ".join(errors[:50]))

    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    temporary_fasta = output_fasta.with_suffix(output_fasta.suffix + ".tmp")
    with temporary_fasta.open("w", encoding="ascii", newline="\n") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id'].strip()}\n{row['sequence'].strip().upper()}\n")
    os.replace(temporary_fasta, output_fasta)

    audit: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tsv": str(source_tsv.resolve()),
        "source_tsv_sha256": sha256_file(source_tsv),
        "output_fasta": str(output_fasta.resolve()),
        "output_fasta_sha256": sha256_file(output_fasta),
        "record_count": len(rows),
        "unique_candidate_ids": len(ids),
        "unique_exact_sequences": len(sequences),
        "unique_backbones": len(backbone_keys),
        "hotspot_set_counts": dict(sorted(set_counts.items())),
        "cdr3_length_distribution": {str(key): value for key, value in sorted(cdr3_lengths.items())},
        "header_policy": "candidate_id_only",
        "scientific_status": "SEQUENCE_INPUT_ONLY_NOT_BINDER_OR_BLOCKER",
        "all_checks_passed": True,
    }
    audit_json.parent.mkdir(parents=True, exist_ok=True)
    temporary_json = audit_json.with_suffix(audit_json.suffix + ".tmp")
    temporary_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_json, audit_json)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_tsv", type=Path)
    parser.add_argument("output_fasta", type=Path)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--expected-set-count", action="append", default=[], metavar="NAME=N")
    args = parser.parse_args()
    audit = prepare(
        args.source_tsv,
        args.output_fasta,
        args.audit_json,
        expected_count=args.expected_count,
        expected_set_counts=parse_expected_set_counts(args.expected_set_count),
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

