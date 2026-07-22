#!/usr/bin/env python3
"""Persistent NanoBodyBuilder2 CPU worker with resumable per-candidate outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import time
from pathlib import Path

import torch
from ImmuneBuilder import NanoBodyBuilder2


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def fasta_records(path: Path):
    name = None
    parts: list[str] = []
    with path.open() as handle:
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pdb_sequence(path: Path) -> tuple[str, int]:
    seen = set()
    residues = []
    atoms = 0
    with path.open() as handle:
        for line in handle:
            if not line.startswith("ATOM"):
                continue
            atoms += 1
            if line[12:16].strip() != "CA":
                continue
            key = (line[21], line[22:27])
            if key in seen:
                continue
            seen.add(key)
            residues.append(AA3.get(line[17:20].strip(), "X"))
    return "".join(residues), atoms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--slurm-job-id", required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = [
        record for index, record in enumerate(fasta_records(args.input))
        if index % args.workers == args.worker_index
    ]
    torch.set_num_threads(args.threads)
    builder = NanoBodyBuilder2(weights_dir=str(args.weights), numbering_scheme="imgt")
    fields = [
        "candidate_id", "sequence_sha256", "structure_model", "structure_model_version",
        "structure_source", "pdb_relative_path", "pdb_sha256", "pdb_bytes",
        "pdb_sequence_match", "atom_records", "mean_predicted_error_angstrom",
        "elapsed_seconds", "worker_id", "slurm_job_id", "status", "failure_reason",
    ]
    manifest_partial = args.output_dir / "manifest.tsv.partial"
    manifest = args.output_dir / "manifest.tsv"
    prior_rows = {}
    if manifest.is_file():
        with manifest.open(newline="") as prior_handle:
            prior_rows = {
                row["candidate_id"]: row
                for row in csv.DictReader(prior_handle, delimiter="\t")
            }
    with manifest_partial.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for candidate_id, sequence in records:
            pdb = args.output_dir / f"{candidate_id}.pdb"
            partial = args.output_dir / f"{candidate_id}.pdb.partial"
            start = time.time()
            status = "SUCCESS"
            failure = ""
            mean_error = prior_rows.get(candidate_id, {}).get("mean_predicted_error_angstrom", "")
            try:
                if not pdb.exists() or pdb.stat().st_size < 10_000:
                    prediction = builder.predict({"H": sequence})
                    mean_error = float(prediction.error_estimates.mean().sqrt().cpu())
                    prediction.save(str(partial), n_threads=args.threads)
                    os.replace(partial, pdb)
                observed, atoms = pdb_sequence(pdb)
                if observed != sequence:
                    raise ValueError("PDB_SEQUENCE_MISMATCH")
                if atoms < 500:
                    raise ValueError("TOO_FEW_ATOMS")
                pdb_hash = sha256(pdb)
                pdb_bytes = pdb.stat().st_size
            except Exception as exc:
                status = "TECHNICAL_NA"
                failure = f"{type(exc).__name__}:{exc}".replace("\r", "\\r").replace("\n", "\\n")
                pdb_hash = ""
                pdb_bytes = pdb.stat().st_size if pdb.exists() else 0
                observed, atoms = "", 0
            writer.writerow({
                "candidate_id": candidate_id,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "structure_model": "NanoBodyBuilder2",
                "structure_model_version": "ImmuneBuilder-1.2",
                "structure_source": "independent_sequence_prediction",
                "pdb_relative_path": pdb.name if status == "SUCCESS" else "",
                "pdb_sha256": pdb_hash,
                "pdb_bytes": pdb_bytes,
                "pdb_sequence_match": str(observed == sequence).lower(),
                "atom_records": atoms,
                "mean_predicted_error_angstrom": mean_error,
                "elapsed_seconds": time.time() - start,
                "worker_id": args.worker_index,
                "slurm_job_id": args.slurm_job_id,
                "status": status,
                "failure_reason": failure,
            })
            handle.flush()
    os.replace(manifest_partial, manifest)
    (args.output_dir / "COMPLETE").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n")


if __name__ == "__main__":
    main()
