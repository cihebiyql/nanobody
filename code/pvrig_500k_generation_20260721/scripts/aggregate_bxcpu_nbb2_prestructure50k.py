#!/usr/bin/env python3
"""Validate and aggregate the eight NanoBodyBuilder2 structure shards."""

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
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fasta_ids(input_dir: Path) -> set[str]:
    ids = set()
    for path in sorted(input_dir.glob("task_*.fasta")):
        for line in path.read_text().splitlines():
            if line.startswith(">"):
                value = line[1:].split()[0]
                if value in ids:
                    raise ValueError(f"duplicate input ID: {value}")
                ids.add(value)
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--full-job-id", required=True)
    args = parser.parse_args()
    expected = fasta_ids(args.campaign / "input")
    results = args.campaign / f"results_{args.full_job_id}"
    archives = args.campaign / f"archives_{args.full_job_id}"
    output = args.campaign / f"aggregated_{args.full_job_id}"
    output.mkdir(parents=True, exist_ok=True)

    manifests = sorted(results.glob("node_*/node_*.manifest.tsv"))
    ready = sorted(archives.glob("node_*.READY.json"))
    if len(manifests) != 8 or len(ready) != 8:
        raise ValueError(f"incomplete outputs: manifests={len(manifests)} ready={len(ready)}")
    rows = []
    manifest_sources = {}
    for path in manifests:
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                rows.append(row)
                manifest_sources[row["candidate_id"]] = path
    ids = [row["candidate_id"] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("structure manifest ID set does not match input")

    combined = output / "prestructure50000_nbb2_manifest.tsv.gz"
    with gzip.open(combined, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader(); writer.writerows(rows)
    counts = Counter(row["status"] for row in rows)
    failures = Counter(row["failure_reason"] for row in rows if row["status"] != "SUCCESS")
    verified_success = 0
    for row in rows:
        if row["status"] != "SUCCESS":
            continue
        source = manifest_sources[row["candidate_id"]]
        worker = int(row["worker_id"])
        pdb = source.parent / "raw" / f"worker_{worker:02d}" / row["pdb_relative_path"]
        if not pdb.is_file():
            raise ValueError(f"missing SUCCESS PDB: {pdb}")
        if pdb.stat().st_size != int(row["pdb_bytes"]):
            raise ValueError(f"PDB byte-size mismatch: {pdb}")
        if sha256(pdb) != row["pdb_sha256"]:
            raise ValueError(f"PDB SHA256 mismatch: {pdb}")
        if row["pdb_sequence_match"] != "true" or int(row["atom_records"]) < 500:
            raise ValueError(f"PDB QC contract mismatch: {pdb}")
        verified_success += 1

    archive_checks = []
    for ready_path in ready:
        ready_payload = json.loads(ready_path.read_text())
        archive_path = archives / ready_payload["archive"]
        observed = sha256(archive_path)
        if observed != ready_payload["archive_sha256"]:
            raise ValueError(f"archive SHA256 mismatch: {archive_path}")
        archive_checks.append({"archive": archive_path.name, "sha256": observed})
    partial_files = sorted(str(path.relative_to(results)) for path in results.rglob("*.partial"))
    overall_status = "PASS" if verified_success == len(expected) else "COMPLETE_WITH_TECHNICAL_NA"
    payload = {
        "status": overall_status, "records": len(rows), "status_counts": dict(sorted(counts.items())),
        "verified_success_pdbs": verified_success,
        "technical_failure_reasons": dict(sorted(failures.items())),
        "input_records": len(expected), "node_archives": len(ready),
        "archive_checks": archive_checks,
        "partial_file_count": len(partial_files),
        "partial_files_sample": partial_files[:20],
        "manifest": str(combined.resolve()), "manifest_sha256": sha256(combined),
        "scientific_boundary": "VHH monomer predictions and technical QC; not binding, affinity, docking, or blocking evidence",
    }
    (output / "COMPLETE.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
