#!/usr/bin/env python3
"""Validate remarked RFantibody PDBs and stage a GPU-sharded RF2 batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdb_sequence(path: Path, chain_id: str) -> str:
    sequence: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    with path.open(encoding="ascii", errors="replace") as handle:
        for line in handle:
            if not line.startswith("ATOM") or len(line) < 27:
                continue
            chain = line[21].strip()
            if chain != chain_id:
                continue
            key = (chain, line[22:26], line[26])
            if key in seen:
                continue
            seen.add(key)
            residue = line[17:20].strip()
            if residue not in AA3_TO_1:
                raise ValueError(f"{path}: unsupported residue {residue!r} in chain {chain_id}")
            sequence.append(AA3_TO_1[residue])
    return "".join(sequence)


def validate_pdb(path: Path, expected_sequence: str) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"missing source PDB: {path}")
    text = path.read_text(encoding="ascii", errors="replace")
    if "REMARK PDBinfo-LABEL:" not in text:
        raise ValueError(f"{path}: missing RFantibody PDBinfo remarks")
    for label in ("H1", "H2", "H3"):
        if label not in text:
            raise ValueError(f"{path}: missing CDR label {label}")
    antibody_sequence = pdb_sequence(path, "H")
    target_sequence = pdb_sequence(path, "T")
    if antibody_sequence != expected_sequence:
        raise ValueError(
            f"{path}: chain H sequence does not match shortlist sequence "
            f"({len(antibody_sequence)} vs {len(expected_sequence)})"
        )
    if not target_sequence:
        raise ValueError(f"{path}: target chain T is missing")
    return {
        "source_pdb_sha256": sha256_file(path),
        "antibody_length": len(antibody_sequence),
        "target_length": len(target_sequence),
    }


def prepare(shortlist_tsv: Path, batch_root: Path, gpu_ids: list[int]) -> dict[str, object]:
    if not gpu_ids or len(set(gpu_ids)) != len(gpu_ids):
        raise ValueError("GPU IDs must be a non-empty unique list")
    with shortlist_tsv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {"candidate_id", "hotspot_set", "backbone_index", "mpnn_index", "sequence", "mpnn_pdb"}
    if not rows:
        raise ValueError("RF2 shortlist is empty")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"shortlist is missing fields: {sorted(missing)}")

    batch_root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(sorted(rows, key=lambda item: item["candidate_id"])):
        candidate_id = row["candidate_id"]
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate candidate ID: {candidate_id}")
        seen_ids.add(candidate_id)
        if not candidate_id.replace("_", "").replace("-", "").replace(".", "").isalnum():
            raise ValueError(f"unsafe candidate ID for PDB filename: {candidate_id!r}")
        source_pdb = Path(row["mpnn_pdb"])
        validation = validate_pdb(source_pdb, row["sequence"].strip().upper())
        gpu_id = gpu_ids[index % len(gpu_ids)]
        shard = f"gpu_{gpu_id}"
        input_dir = batch_root / "shards" / shard / "input"
        output_dir = batch_root / "shards" / shard / "output"
        log_dir = batch_root / "shards" / shard / "logs"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        staged_pdb = input_dir / f"{candidate_id}.pdb"
        if staged_pdb.exists() or staged_pdb.is_symlink():
            if staged_pdb.resolve() != source_pdb.resolve():
                raise ValueError(f"staged input points to a different source: {staged_pdb}")
        else:
            staged_pdb.symlink_to(source_pdb)
        manifest_rows.append(
            {
                **row,
                "gpu_id": gpu_id,
                "shard": shard,
                "source_pdb": str(source_pdb),
                "staged_pdb": str(staged_pdb),
                "expected_output_pdb": str(output_dir / f"{candidate_id}_best.pdb"),
                **validation,
            }
        )

    fields = list(manifest_rows[0])
    manifest_path = batch_root / "rf2_input_manifest.tsv"
    temporary = manifest_path.with_suffix(".tsv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(manifest_rows)
    os.replace(temporary, manifest_path)

    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shortlist_tsv": str(shortlist_tsv),
        "shortlist_tsv_sha256": sha256_file(shortlist_tsv),
        "candidate_count": len(manifest_rows),
        "gpu_ids": gpu_ids,
        "candidates_by_gpu": {
            str(key): value for key, value in sorted(Counter(int(row["gpu_id"]) for row in manifest_rows).items())
        },
        "input_policy": "symlink_to_immutable_rfantibody_mpnn_pose",
        "rf2_parameters": {"num_recycles": 10, "hotspot_show_prop": 0.0, "seed": 42},
        "all_checks_passed": True,
    }
    (batch_root / "rf2_batch_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shortlist_tsv", type=Path)
    parser.add_argument("batch_root", type=Path)
    parser.add_argument("--gpu-ids", default="1,2,3,4,6,7")
    args = parser.parse_args()
    gpu_ids = [int(value) for value in args.gpu_ids.split(",") if value.strip()]
    print(json.dumps(prepare(args.shortlist_tsv, args.batch_root, gpu_ids), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
