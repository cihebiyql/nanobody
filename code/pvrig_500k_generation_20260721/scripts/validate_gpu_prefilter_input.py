#!/usr/bin/env python3
"""Validate the normalized GPU pool before expensive remote prefiltering."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fasta_records(path: Path):
    name = None
    parts: list[str] = []
    with gzip.open(path, "rt") if path.suffix == ".gz" else path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(parts)
                name = line[1:].split()[0]
                parts = []
            else:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--fasta", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rf-minimum", type=int, default=150_000)
    parser.add_argument("--mpnn-minimum", type=int, default=150_000)
    args = parser.parse_args()

    receipt = json.loads(args.receipt.read_text())
    if receipt.get("status") != "READY_FOR_ANARCI":
        raise ValueError(f"normalization receipt is not ready: {receipt.get('status')}")

    expected_hashes = receipt.get("outputs", {})
    observed_hashes = {
        args.candidates.name: sha256(args.candidates),
        args.fasta.name: sha256(args.fasta),
    }
    for name, digest in observed_hashes.items():
        if expected_hashes.get(name) != digest:
            raise ValueError(f"receipt hash mismatch for {name}")

    candidate_ids: set[str] = set()
    candidate_sequences: set[str] = set()
    route_counts: Counter[str] = Counter()
    with gzip.open(args.candidates, "rt", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            candidate_id = row["candidate_id"]
            sequence = row["sequence"]
            if candidate_id in candidate_ids:
                raise ValueError(f"duplicate candidate ID: {candidate_id}")
            if sequence in candidate_sequences:
                raise ValueError(f"duplicate sequence: {candidate_id}")
            if row.get("fast_qc_status") != "PASS":
                raise ValueError(f"non-PASS row in prefilter input: {candidate_id}")
            candidate_ids.add(candidate_id)
            candidate_sequences.add(sequence)
            route_counts[row["route_id"]] += 1

    required = {
        "rfantibody": args.rf_minimum,
        "fixed_pose_mpnn": args.mpnn_minimum,
    }
    for route, minimum in required.items():
        if route_counts[route] < minimum:
            raise ValueError(f"{route}: {route_counts[route]} < {minimum}")
    if dict(sorted(route_counts.items())) != receipt.get("route_fast_qc_pass"):
        raise ValueError("route counts do not match normalization receipt")

    fasta_ids: set[str] = set()
    fasta_sequences: set[str] = set()
    for candidate_id, sequence in fasta_records(args.fasta):
        if candidate_id in fasta_ids:
            raise ValueError(f"duplicate FASTA ID: {candidate_id}")
        if sequence in fasta_sequences:
            raise ValueError(f"duplicate FASTA sequence: {candidate_id}")
        fasta_ids.add(candidate_id)
        fasta_sequences.add(sequence)
    if fasta_ids != candidate_ids:
        raise ValueError(
            f"FASTA/TSV ID mismatch: missing={len(candidate_ids-fasta_ids)} "
            f"extra={len(fasta_ids-candidate_ids)}"
        )
    if fasta_sequences != candidate_sequences:
        raise ValueError("FASTA/TSV sequence set mismatch")

    payload = {
        "status": "PASS",
        "records": len(candidate_ids),
        "candidate_id_exact_unique": True,
        "sequence_exact_unique": True,
        "fasta_tsv_exact_id_closure": True,
        "fasta_tsv_exact_sequence_closure": True,
        "route_counts": dict(sorted(route_counts.items())),
        "file_sha256": observed_hashes,
        "scientific_boundary": (
            "sequence provenance and hard-QC validation only; not binding, affinity, "
            "docking, purity, expression, or blocking evidence"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
