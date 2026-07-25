#!/usr/bin/env python3
"""Freeze short-MD inputs for Top10 candidates not present in the prior MD panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MD_SEEDS = (917, 1931, 3253)
# GPUs 0, 5 and 7 were occupied by unrelated users at launch audit time.
GPUS = (1, 2, 3, 4, 6)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_chain_order(source: Path) -> bytes:
    lines = source.read_text(encoding="ascii", errors="ignore").splitlines()
    by_chain: dict[str, list[str]] = {"T": [], "A": []}
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 22:
            chain = line[21:22]
            if chain in by_chain:
                by_chain[chain].append(line)
    if not by_chain["T"] or not by_chain["A"]:
        raise RuntimeError(f"source pose lacks T/A chains: {source}")
    return ("\n".join([*by_chain["T"], "TER", *by_chain["A"], "TER", "END", ""])).encode(
        "ascii"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final50", type=Path, required=True)
    parser.add_argument("--existing-md-systems", type=Path, required=True)
    parser.add_argument("--static-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    final50 = read_tsv(args.final50)
    existing = read_tsv(args.existing_md_systems)
    static_rows = read_tsv(args.static_manifest)
    if len(final50) != 50:
        raise ValueError(f"expected 50 final candidates, observed {len(final50)}")
    existing_ids = {row["candidate_id"] for row in existing}
    static_8x6b = {
        row["candidate_id"]: row
        for row in static_rows
        if row["conformation"].lower() == "8x6b"
    }
    top10 = sorted(
        (row for row in final50 if int(row["final_rank"]) <= 10),
        key=lambda row: int(row["final_rank"]),
    )
    missing = [row for row in top10 if row["candidate_id"] not in existing_ids]
    if len(top10) != 10:
        raise ValueError(f"expected Top10, observed {len(top10)}")
    if len(missing) != 6:
        raise ValueError(
            "frozen evidence currently requires six Top10 completions; "
            f"observed {len(missing)}"
        )

    mdroot = args.out
    pdb_dir = mdroot / "inputs"
    pdb_dir.mkdir(parents=True, exist_ok=True)
    systems: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for index, row in enumerate(missing):
        candidate_id = row["candidate_id"]
        if candidate_id not in static_8x6b:
            raise RuntimeError(f"missing 8X6B static pose: {candidate_id}")
        static = static_8x6b[candidate_id]
        source = Path(static["frozen_pdb"])
        observed_source_hash = sha256_file(source)
        if observed_source_hash != static["frozen_pdb_sha256"]:
            raise RuntimeError(f"static source hash mismatch: {candidate_id}")
        payload = normalize_chain_order(source)
        output = pdb_dir / f"{candidate_id}.pdb"
        frozen_hash = hashlib.sha256(payload).hexdigest()
        if output.exists() and sha256_file(output) != frozen_hash:
            raise RuntimeError(f"frozen MD input mismatch: {output}")
        if not output.exists():
            output.write_bytes(payload)
        systems.append(
            {
                "system_id": candidate_id,
                "candidate_id": candidate_id,
                "final_rank": row["final_rank"],
                "md_selection_channel": "TOP10_COMPLETION",
                "route": row.get("route", ""),
                "parent_cluster": row.get("parent_cluster", ""),
                "cdr3_diversity_cluster": row.get("cdr3_diversity_cluster", ""),
                "cdr3": row.get("cdr3", ""),
                "source_job_id": static["static_job_id"],
                "source_conformation": "8x6b",
                "source_pdb": str(output),
                "source_pdb_sha256": frozen_hash,
                "source_docking_job_hash": static.get("source_job_hash", ""),
                "md_role": "DESCRIPTIVE_ONLY",
            }
        )
        for seed_index, seed in enumerate(MD_SEEDS):
            jobs.append(
                {
                    "system_id": candidate_id,
                    "candidate_id": candidate_id,
                    "md_selection_channel": "TOP10_COMPLETION",
                    "source_job_id": static["static_job_id"],
                    "md_seed": seed,
                    "gpu": GPUS[(index * len(MD_SEEDS) + seed_index) % len(GPUS)],
                    "production_ns": 2,
                    "analysis_window_ns": "1.0-2.0",
                    "md_role": "DESCRIPTIVE_ONLY",
                }
            )
    if len(jobs) != len(systems) * len(MD_SEEDS):
        raise RuntimeError("MD manifest cardinality mismatch")
    if len({(row["system_id"], row["md_seed"]) for row in jobs}) != len(jobs):
        raise RuntimeError("MD manifest contains duplicate system/seed jobs")

    systems_path = mdroot / "md_systems.tsv"
    jobs_path = mdroot / "md_manifest.tsv"
    write_tsv(systems_path, systems)
    write_tsv(jobs_path, jobs)
    receipt = {
        "schema_version": "pvrig.top10.md_completion.prepare.v1",
        "state": "TOP10_MD_COMPLETION_PREPARED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "top10_candidates": 10,
        "already_complete_candidates": 4,
        "completion_candidates": len(systems),
        "trajectories": len(jobs),
        "seeds": list(MD_SEEDS),
        "gpus": list(GPUS),
        "production_ns_each": 2,
        "method_role": "DESCRIPTIVE_ONLY",
        "evidence_note": (
            "The frozen Final50 and prior MD manifests show four, not five, "
            "Top10 candidates already complete; six candidates are therefore run."
        ),
        "input_hashes": {
            str(args.final50): sha256_file(args.final50),
            str(args.existing_md_systems): sha256_file(args.existing_md_systems),
            str(args.static_manifest): sha256_file(args.static_manifest),
        },
        "output_hashes": {
            systems_path.name: sha256_file(systems_path),
            jobs_path.name: sha256_file(jobs_path),
        },
        "claim_boundary": (
            "Short binary-complex MD is descriptive pose-persistence evidence, "
            "not experimental affinity or blocking."
        ),
    }
    receipt_path = mdroot / "TOP10_MD_COMPLETION_PREPARE_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidates": len(systems), "trajectories": len(jobs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
