#!/usr/bin/env python3
"""Stage hash-closed monomer PDBs under a path with no Docking/pose tokens."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


FIELDS = (
    "candidate_id", "sequence_sha256", "monomer_relative_path",
    "monomer_sha256", "source_chain", "claim_boundary",
)
CLAIM = (
    "Label-free VHH monomer copied from the frozen canonical10644 structure "
    "manifest; no candidate pose, contact teacher, Docking result, or Docking Gold truth."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage(source_manifest: Path, expected_sha256: str, output_root: Path, workers: int, expected_rows: int = 10644) -> dict:
    if sha256_file(source_manifest) != expected_sha256:
        raise ValueError("source_manifest_sha256_mismatch")
    if output_root.exists():
        raise ValueError("output_root_exists")
    with source_manifest.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != expected_rows:
        raise ValueError(f"row_count:{len(rows)}")
    ids = [row["candidate_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_candidate_id")
    staging = output_root.with_name(f".{output_root.name}.{os.getpid()}.tmp")
    pdb_root = staging / "pdb_bundle"
    monomer_root = pdb_root / "clean_monomers"
    monomer_root.mkdir(parents=True)

    def copy_one(row: dict[str, str]) -> tuple[dict[str, str], int]:
        candidate_id = row["candidate_id"]
        if Path(candidate_id).name != candidate_id or "/" in candidate_id or "\\" in candidate_id:
            raise ValueError(f"unsafe_candidate_id:{candidate_id}")
        source = Path(row["monomer_path"])
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"invalid_source_monomer:{candidate_id}")
        expected = row["monomer_sha256"]
        if sha256_file(source) != expected:
            raise ValueError(f"source_monomer_sha256_mismatch:{candidate_id}")
        relative = Path("clean_monomers") / f"{candidate_id}.pdb"
        destination = pdb_root / relative
        shutil.copyfile(source, destination)
        if sha256_file(destination) != expected:
            raise ValueError(f"staged_monomer_sha256_mismatch:{candidate_id}")
        return ({
            "candidate_id": candidate_id,
            "sequence_sha256": row["sequence_sha256"],
            "monomer_relative_path": relative.as_posix(),
            "monomer_sha256": expected,
            "source_chain": row["monomer_chain"],
            "claim_boundary": CLAIM,
        }, destination.stat().st_size)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            staged = list(pool.map(copy_one, rows))
        manifest = staging / "canonical10644_clean_structure_manifest_v1.tsv"
        with manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(FIELDS), delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(item[0] for item in staged)
        receipt = {
            "schema_version": "pvrig_v2_11_canonical10644_clean_monomer_staging_v1",
            "status": "PASS_CANONICAL10644_CLEAN_MONOMERS_STAGED",
            "counts": {"candidates": len(staged), "bytes": sum(item[1] for item in staged)},
            "inputs": {"structure_manifest": str(source_manifest.resolve()), "sha256": expected_sha256},
            "outputs": {
                "canonical10644_clean_structure_manifest_v1.tsv": sha256_file(manifest),
                "pdb_root": "pdb_bundle",
            },
            "claim_boundary": CLAIM,
        }
        (staging / "STAGING_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        os.replace(staging, output_root)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--expected-rows", type=int, default=10644)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        raise ValueError("workers_out_of_range")
    print(json.dumps(stage(args.source_manifest, args.expected_source_manifest_sha256, args.output_root, args.workers, args.expected_rows), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
