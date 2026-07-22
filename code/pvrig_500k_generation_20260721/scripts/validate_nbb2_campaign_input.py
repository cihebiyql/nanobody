#!/usr/bin/env python3
"""Fail-closed validation before a generic NBB2 campaign is submitted."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


AA20 = set("ACDEFGHIKLMNPQRSTVWY")
ALLOWED_STATUSES = {
    "READY", "PASS", "READY_FOR_NBB2_TNP", "READY_FOR_REPLACEMENT_NBB2_TNP",
    "READY_FOR_STRUCTURE_PREDICTION",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def op(path: Path, mode: str):
    return gzip.open(path, mode, newline="") if path.suffix == ".gz" else path.open(mode, newline="")


def fasta_records(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    current = ""
    chunks: list[str] = []
    with op(path, "rt") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current:
                    sequence = "".join(chunks).upper()
                    if current in records:
                        raise SystemExit(f"duplicate FASTA candidate_id: {current}")
                    records[current] = sequence
                current = line[1:].split()[0]
                chunks = []
            else:
                if not current:
                    raise SystemExit(f"FASTA sequence before header: {path}")
                chunks.append(line)
    if current:
        sequence = "".join(chunks).upper()
        if current in records:
            raise SystemExit(f"duplicate FASTA candidate_id: {current}")
        records[current] = sequence
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--source-fasta", type=Path)
    parser.add_argument("--expected", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ready = json.loads(args.ready.read_text())
    if ready.get("status") not in ALLOWED_STATUSES:
        raise SystemExit(f"input READY status is not accepted: {ready.get('status')!r}")
    if int(ready.get("records", -1)) != args.expected:
        raise SystemExit(f"READY records {ready.get('records')} != {args.expected}")
    expected_selection_sha = ready.get("selection_sha256")
    if not expected_selection_sha or expected_selection_sha != sha(args.selection):
        raise SystemExit("selection SHA256 does not match READY")

    selection: dict[str, str] = {}
    sequences: set[str] = set()
    with op(args.selection, "rt") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"candidate_id", "sequence", "sequence_sha256"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"selection fields missing: {sorted(missing)}")
        for row in reader:
            candidate_id = row["candidate_id"]
            sequence = row["sequence"].strip().upper()
            if candidate_id in selection:
                raise SystemExit(f"duplicate selection candidate_id: {candidate_id}")
            if sequence in sequences:
                raise SystemExit(f"duplicate selection sequence: {candidate_id}")
            if not sequence or not set(sequence) <= AA20:
                raise SystemExit(f"invalid selection sequence: {candidate_id}")
            if hashlib.sha256(sequence.encode()).hexdigest() != row["sequence_sha256"]:
                raise SystemExit(f"selection sequence SHA256 mismatch: {candidate_id}")
            selection[candidate_id] = sequence
            sequences.add(sequence)
    if len(selection) != args.expected:
        raise SystemExit(f"selection records {len(selection)} != {args.expected}")

    manifest_path = args.shard_dir / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    if int(manifest.get("records", -1)) != args.expected or int(manifest.get("shards", -1)) != args.shards:
        raise SystemExit(f"shard manifest mismatch: {manifest}")
    task_paths = sorted(args.shard_dir.glob("task_*.fasta"))
    if len(task_paths) != args.shards:
        raise SystemExit(f"task FASTA count {len(task_paths)} != {args.shards}")
    sharded: dict[str, str] = {}
    for path in task_paths:
        for candidate_id, sequence in fasta_records(path).items():
            if candidate_id in sharded:
                raise SystemExit(f"duplicate candidate across task FASTAs: {candidate_id}")
            sharded[candidate_id] = sequence
    if sharded != selection:
        raise SystemExit(
            f"selection/task FASTA closure mismatch selection={len(selection)} tasks={len(sharded)}"
        )

    source_fasta_sha = ""
    if args.source_fasta:
        source_fasta_sha = sha(args.source_fasta)
        if ready.get("fasta_sha256") != source_fasta_sha:
            raise SystemExit("source FASTA SHA256 does not match READY")
        if fasta_records(args.source_fasta) != selection:
            raise SystemExit("source FASTA/selection exact closure mismatch")

    payload = {
        "status": "PASS",
        "records": args.expected,
        "shards": args.shards,
        "candidate_id_exact_unique": True,
        "sequence_exact_unique": True,
        "selection_task_fasta_exact_match": True,
        "selection_sha256": expected_selection_sha,
        "source_fasta_sha256": source_fasta_sha,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
