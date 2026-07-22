#!/usr/bin/env python3
"""Merge original and recovered NBB2 manifests and package only recovery PDBs."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--initial-job-id", required=True)
    parser.add_argument("--recovery-job-id", required=True)
    args = parser.parse_args()
    initial = args.campaign / f"results_{args.initial_job_id}"
    base = args.campaign / f"recovery_{args.initial_job_id}"
    recovery = base / f"results_{args.recovery_job_id}"
    out = base / f"final_{args.recovery_job_id}"
    archives = out / "archives"
    out.mkdir(parents=True, exist_ok=True); archives.mkdir(exist_ok=True)

    recovered: dict[str, dict[str, str]] = {}
    for path in sorted(recovery.glob("node_*/recovery_manifest.tsv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                recovered[row["candidate_id"]] = row

    final_rows = []
    status_counts: dict[str, int] = {}
    for manifest in sorted(initial.glob("node_*/raw/worker_*/manifest.tsv")):
        node = manifest.parents[2].name.split("_")[-1]
        with manifest.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                cid = row["candidate_id"]
                final = dict(row)
                final["original_node"] = node
                final["final_pdb_path"] = ""
                final["recovery_status"] = "NOT_NEEDED"
                if row["status"] == "SUCCESS":
                    worker = int(row["worker_id"])
                    final["final_pdb_path"] = str(
                        (manifest.parent.parent / f"worker_{worker:02d}" / row["pdb_relative_path"]).resolve()
                    )
                else:
                    rec = recovered.get(cid)
                    if rec and rec["status"] == "SUCCESS":
                        final["status"] = "SUCCESS_RECOVERED"
                        final["failure_reason"] = ""
                        final["pdb_relative_path"] = Path(rec["recovered_pdb"]).name
                        final["pdb_sha256"] = rec["pdb_sha256"]
                        final["pdb_bytes"] = rec["pdb_bytes"]
                        final["pdb_sequence_match"] = rec["pdb_sequence_match"]
                        final["atom_records"] = rec["atom_records"]
                        final["final_pdb_path"] = rec["recovered_pdb"]
                        final["recovery_status"] = "SUCCESS"
                    else:
                        final["recovery_status"] = rec["status"] if rec else "NOT_RECOVERABLE"
                status_counts[final["status"]] = status_counts.get(final["status"], 0) + 1
                final_rows.append(final)

    fields = list(final_rows[0])
    manifest_out = out / "prestructure50000_nbb2_final_manifest.tsv.gz"
    with gzip.open(manifest_out, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(final_rows)

    archive_entries = []
    for node_dir in sorted(recovery.glob("node_*")):
        node = node_dir.name.split("_")[-1]
        archive = archives / f"recovery_node_{node}.tar.gz"
        with archive.open("wb") as handle:
            p1 = subprocess.Popen(["tar", "-C", str(recovery), "-cf", "-", node_dir.name], stdout=subprocess.PIPE)
            p2 = subprocess.Popen(["gzip", "-1"], stdin=p1.stdout, stdout=handle)
            assert p1.stdout is not None; p1.stdout.close()
            if p2.wait() != 0 or p1.wait() != 0:
                raise RuntimeError(f"failed to archive {node_dir}")
        archive_entries.append({"archive": archive.name, "sha256": sha256(archive), "bytes": archive.stat().st_size})

    success = status_counts.get("SUCCESS", 0) + status_counts.get("SUCCESS_RECOVERED", 0)
    receipt = {
        "status": "PASS" if success == len(final_rows) else "COMPLETE_WITH_TECHNICAL_NA",
        "records": len(final_rows),
        "successful_structures": success,
        "status_counts": status_counts,
        "manifest": str(manifest_out.resolve()),
        "manifest_sha256": sha256(manifest_out),
        "recovery_archives": archive_entries,
        "scientific_boundary": "VHH monomer predictions and technical QC; not binding, affinity, docking, or blocking evidence",
    }
    (out / "COMPLETE.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    with (out / "SHA256SUMS").open("w") as handle:
        handle.write(f"{receipt['manifest_sha256']}  {manifest_out.name}\n")
        for item in archive_entries:
            handle.write(f"{item['sha256']}  archives/{item['archive']}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
