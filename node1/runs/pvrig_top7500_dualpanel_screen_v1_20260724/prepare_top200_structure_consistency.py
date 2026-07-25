#!/usr/bin/env python3
"""Freeze Top200 inputs and resolve existing NanoBodyBuilder2 monomers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pdb_sequences(path: Path) -> dict[str, str]:
    chains: dict[str, list[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
            continue
        altloc = line[16]
        if altloc not in (" ", "A"):
            continue
        chain = line[21].strip() or "_"
        key = (chain, line[22:26], line[26])
        if key in seen:
            continue
        seen.add(key)
        residue = AA3.get(line[17:20].strip().upper())
        if residue:
            chains.setdefault(chain, []).append(residue)
    return {chain: "".join(sequence) for chain, sequence in chains.items()}


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top200", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--nbb2-root", type=Path, action="append", required=True)
    parser.add_argument("--shards", type=int, default=8)
    args = parser.parse_args()

    with args.top200.open(newline="", encoding="utf-8-sig") as handle:
        top200 = list(csv.DictReader(handle, delimiter="\t"))
    if len(top200) != 200 or len({row["candidate_id"] for row in top200}) != 200:
        raise ValueError("Top200 input must contain exactly 200 unique candidates")

    project = args.project.resolve()
    inputs = project / "inputs"
    manifests = project / "manifests"
    inputs.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.top200, inputs / "top200_pre_static.tsv")

    manifest_rows: list[dict[str, object]] = []
    source_counts: Counter[str] = Counter()
    fasta_path = inputs / "top200.fasta"
    with fasta_path.open("w", encoding="ascii", newline="\n") as fasta:
        for row in sorted(top200, key=lambda item: int(item["top200_rank"])):
            candidate = row["candidate_id"]
            sequence = row["sequence"]
            matches = [
                root.resolve() / f"{candidate}.pdb"
                for root in args.nbb2_root
                if (root.resolve() / f"{candidate}.pdb").is_file()
            ]
            if not matches:
                raise FileNotFoundError(f"NBB2 monomer missing: {candidate}")
            source = matches[0]
            chain_sequences = pdb_sequences(source)
            matching_chains = [
                chain for chain, observed in chain_sequences.items()
                if observed == sequence
            ]
            if not matching_chains:
                raise ValueError(
                    f"NBB2 sequence mismatch: {candidate} {chain_sequences}"
                )
            source_counts[str(source.parent)] += 1
            fasta.write(f">{candidate}\n{sequence}\n")
            manifest_rows.append(
                {
                    "top200_rank": row["top200_rank"],
                    "candidate_id": candidate,
                    "sequence": sequence,
                    "sequence_sha256": row["sequence_sha256"],
                    "imgt_cdr1": row["IMGT_CDR1"],
                    "imgt_cdr2": row["IMGT_CDR2"],
                    "imgt_cdr3": row["IMGT_CDR3"],
                    "route": row["route"],
                    "shard": (int(row["top200_rank"]) - 1) % args.shards,
                    "nbb2_pdb": str(source),
                    "nbb2_pdb_sha256": sha256_file(source),
                    "nbb2_chain": matching_chains[0],
                    "nbb2_sequence_match": "true",
                    "alternate_nbb2_source_count": max(0, len(matches) - 1),
                }
            )

    fields = [
        "top200_rank", "candidate_id", "sequence", "sequence_sha256",
        "imgt_cdr1", "imgt_cdr2", "imgt_cdr3", "route", "shard",
        "nbb2_pdb", "nbb2_pdb_sha256", "nbb2_chain",
        "nbb2_sequence_match", "alternate_nbb2_source_count",
    ]
    manifest_path = manifests / "top200_structure_manifest.tsv"
    write_tsv(manifest_path, manifest_rows, fields)

    receipt = {
        "schema_version": "pvrig.top200.structure_consistency.prepare.v1",
        "state": "READY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(manifest_rows),
        "shard_count": args.shards,
        "shard_sizes": dict(
            sorted(Counter(str(row["shard"]) for row in manifest_rows).items())
        ),
        "nbb2_sequence_match_count": sum(
            row["nbb2_sequence_match"] == "true" for row in manifest_rows
        ),
        "nbb2_source_counts": dict(sorted(source_counts.items())),
        "input_top200_sha256": sha256_file(args.top200),
        "frozen_top200_sha256": sha256_file(inputs / "top200_pre_static.tsv"),
        "fasta_sha256": sha256_file(fasta_path),
        "manifest_sha256": sha256_file(manifest_path),
    }
    (project / "PREPARE_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
