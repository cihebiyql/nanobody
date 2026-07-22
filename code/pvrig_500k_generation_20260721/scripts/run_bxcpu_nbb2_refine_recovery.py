#!/usr/bin/env python3
"""Recover NBB2 PDBs whose strained-sidechain OpenMM path hit the Threads typo."""

from __future__ import annotations

import argparse
import csv
import hashlib
import multiprocessing as mp
import os
from pathlib import Path
import time


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V",
}
FIELDS = [
    "candidate_id", "status", "failure_reason", "source_partial", "recovered_pdb",
    "pdb_sha256", "pdb_bytes", "pdb_sequence_match", "atom_records", "elapsed_seconds",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pdb_sequence(path: Path) -> tuple[str, int]:
    seen = set(); residues = []; atoms = 0
    with path.open() as handle:
        for line in handle:
            if not line.startswith("ATOM"):
                continue
            atoms += 1
            if line[12:16].strip() != "CA":
                continue
            key = (line[21], line[22:27])
            if key not in seen:
                seen.add(key); residues.append(AA3.get(line[17:20].strip(), "X"))
    return "".join(residues), atoms


def recover(task: tuple[dict[str, str], str, int]) -> dict[str, str | int | float]:
    row, output_dir, threads = task
    from ImmuneBuilder.refine import refine

    started = time.time()
    cid = row["candidate_id"]
    source = Path(row["source_partial"])
    output = Path(output_dir) / f"{cid}.pdb"
    partial = output.with_suffix(".pdb.partial")
    result: dict[str, str | int | float] = {
        "candidate_id": cid,
        "status": "SUCCESS",
        "failure_reason": "",
        "source_partial": str(source),
        "recovered_pdb": str(output.resolve()),
        "pdb_sha256": "",
        "pdb_bytes": 0,
        "pdb_sequence_match": "false",
        "atom_records": 0,
        "elapsed_seconds": 0.0,
    }
    try:
        success = refine(str(source), str(partial), n_threads=threads)
        if not success:
            raise RuntimeError("ImmuneBuilder_refine_returned_false")
        observed, atoms = pdb_sequence(partial)
        if observed != row["sequence"]:
            raise ValueError("PDB_SEQUENCE_MISMATCH")
        if atoms < 500:
            raise ValueError("TOO_FEW_ATOMS")
        os.replace(partial, output)
        result.update(
            pdb_sha256=sha256(output),
            pdb_bytes=output.stat().st_size,
            pdb_sequence_match="true",
            atom_records=atoms,
        )
    except Exception as exc:
        result["status"] = "TECHNICAL_NA"
        result["failure_reason"] = f"{type(exc).__name__}:{exc}"
        partial.unlink(missing_ok=True)
    result["elapsed_seconds"] = time.time() - started
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with args.input.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    tasks = [(row, str(args.output_dir), args.threads) for row in rows]
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        if tasks:
            with mp.Pool(args.workers) as pool:
                for result in pool.imap_unordered(recover, tasks, chunksize=1):
                    writer.writerow(result); handle.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
