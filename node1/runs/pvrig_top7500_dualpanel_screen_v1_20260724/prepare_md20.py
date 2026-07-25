#!/usr/bin/env python3
"""Prepare a 20-candidate, 60-trajectory descriptive short-MD panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


CHANNEL_TARGETS = [
    ("CORE_EXPLOITATION", 14),
    ("PARENT_CDR3_DIVERSITY", 3),
    ("MODEL_DISAGREEMENT_RESCUE", 2),
    ("STRUCTURAL_RESERVE", 1),
]
MD_SEEDS = (917, 1931, 3253)
GPUS = (0, 1, 2, 4)


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


def score(row: dict[str, str]) -> float:
    for key, scale in (
        ("post_static_selection_score", 1.0),
        ("selection_score", 1.0),
        ("rescreen_competition_proxy", 100.0),
    ):
        try:
            value = float(row.get(key, "")) * scale
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return -math.inf


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
    output = [*by_chain["T"], "TER", *by_chain["A"], "TER", "END", ""]
    return "\n".join(output).encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top80", type=Path, required=True)
    parser.add_argument("--top80-receipt", type=Path, required=True)
    parser.add_argument("--static-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.top80_receipt.read_text(encoding="utf-8"))
    if receipt.get("state") != "TOP80_COMPLETE" or receipt.get("count") != 80:
        raise ValueError("Top80 receipt is not complete")
    top80 = read_tsv(args.top80)
    static_rows = read_tsv(args.static_manifest)
    if len(top80) != 80 or len(static_rows) != 400:
        raise ValueError("expected Top80 and 400-row static manifest")
    static_8x6b = {
        row["candidate_id"]: row
        for row in static_rows
        if row["conformation"] == "8x6b"
    }
    ranked = sorted(top80, key=lambda row: (-score(row), row["candidate_id"]))
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    parent_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    cluster_counts: Counter[str] = Counter()

    def allowed(row: dict[str, str]) -> bool:
        return (
            row["candidate_id"] not in selected_ids
            and row["candidate_id"] in static_8x6b
            and parent_counts[row.get("parent_cluster", "")] < 6
            and route_counts[row.get("route", "")] < 14
            and cluster_counts[row.get("cdr3_diversity_cluster", "")] < 1
        )

    def add(row: dict[str, str], reason: str) -> None:
        copied = dict(row)
        copied["md_selection_channel"] = reason
        selected.append(copied)
        selected_ids.add(row["candidate_id"])
        parent_counts[row.get("parent_cluster", "")] += 1
        route_counts[row.get("route", "")] += 1
        cluster_counts[row.get("cdr3_diversity_cluster", "")] += 1

    for channel, target in CHANNEL_TARGETS:
        before = len(selected)
        for row in ranked:
            if len(selected) - before >= target:
                break
            if row.get("top80_selection_channel") == channel and allowed(row):
                add(row, channel)
    for row in ranked:
        if len(selected) >= 20:
            break
        if allowed(row):
            add(row, "QUOTA_SAFE_BACKFILL")
    if len(selected) != 20:
        raise ValueError(f"MD panel selection produced {len(selected)} candidates")

    args.out.mkdir(parents=True, exist_ok=True)
    pdb_dir = args.out / "inputs"
    pdb_dir.mkdir(parents=True, exist_ok=True)
    systems: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for index, row in enumerate(selected):
        candidate_id = row["candidate_id"]
        static = static_8x6b[candidate_id]
        source = Path(static["frozen_pdb"])
        if sha256_file(source) != static["frozen_pdb_sha256"]:
            raise RuntimeError(f"static source hash mismatch: {candidate_id}")
        payload = normalize_chain_order(source)
        output = pdb_dir / f"{candidate_id}.pdb"
        observed_hash = hashlib.sha256(payload).hexdigest()
        if output.exists() and sha256_file(output) != observed_hash:
            raise RuntimeError(f"frozen MD input mismatch: {output}")
        if not output.exists():
            output.write_bytes(payload)
        systems.append(
            {
                "system_id": candidate_id,
                "candidate_id": candidate_id,
                "top80_rank": row.get("top80_rank", ""),
                "md_selection_channel": row["md_selection_channel"],
                "route": row.get("route", ""),
                "parent_cluster": row.get("parent_cluster", ""),
                "cdr3_diversity_cluster": row.get("cdr3_diversity_cluster", ""),
                "cdr3": row.get("cdr3", ""),
                "source_job_id": static["static_job_id"],
                "source_conformation": "8x6b",
                "source_pdb": str(output),
                "source_pdb_sha256": observed_hash,
                "source_docking_job_hash": static.get("source_job_hash", ""),
                "md_role": "DESCRIPTIVE_ONLY",
            }
        )
        for seed_index, seed in enumerate(MD_SEEDS):
            jobs.append(
                {
                    "system_id": candidate_id,
                    "candidate_id": candidate_id,
                    "md_selection_channel": row["md_selection_channel"],
                    "source_job_id": static["static_job_id"],
                    "md_seed": seed,
                    "gpu": GPUS[(index * len(MD_SEEDS) + seed_index) % len(GPUS)],
                    "production_ns": 2,
                    "analysis_window_ns": "1.0-2.0",
                    "md_role": "DESCRIPTIVE_ONLY",
                }
            )
    if len(jobs) != 60 or len({(row["system_id"], row["md_seed"]) for row in jobs}) != 60:
        raise RuntimeError("MD manifest must contain 60 unique system/seed jobs")
    systems_path = args.out / "md_systems.tsv"
    jobs_path = args.out / "md_manifest.tsv"
    write_tsv(systems_path, systems)
    write_tsv(jobs_path, jobs)
    md_receipt = {
        "schema_version": "pvrig.top80.md20_prepare.v1",
        "state": "MD20_PREPARED",
        "candidates": 20,
        "trajectories": 60,
        "seeds": list(MD_SEEDS),
        "gpus": list(GPUS),
        "production_ns_each": 2,
        "method_role": "DESCRIPTIVE_ONLY",
        "input_hashes": {
            str(args.top80): sha256_file(args.top80),
            str(args.top80_receipt): sha256_file(args.top80_receipt),
            str(args.static_manifest): sha256_file(args.static_manifest),
        },
        "output_hashes": {
            systems_path.name: sha256_file(systems_path),
            jobs_path.name: sha256_file(jobs_path),
        },
        "claim_boundary": (
            "Short MD is pose-persistence evidence only and is not experimental "
            "affinity or blocking."
        ),
    }
    receipt_path = args.out / "MD20_PREPARE_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(md_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidates": 20, "trajectories": 60}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
