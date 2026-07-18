#!/usr/bin/env python3
"""Build a hash-closed pool of previously unselected V4-H RFantibody sequences."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


HIGH_YIELD_PARENTS = {"C0176", "C0283", "C0086", "C0348", "C0360"}
CLAIM_BOUNDARY = (
    "Sequence/developability candidates for computational PVRIG docking expansion only; "
    "not binding, affinity, competition, or experimental blocking."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def priority_tier(row: dict[str, str]) -> str:
    high_parent = row["parent_framework_cluster"] in HIGH_YIELD_PARENTS
    long_cdr3 = int(row["cdr3_length"]) >= 19
    if high_parent and long_cdr3:
        return "P1_EXPLOIT"
    if high_parent:
        return "P2_PARENT"
    if long_cdr3:
        return "P3_LONG_CDR3"
    return "P4_DIVERSITY"


def build(raw_path: Path, selected_path: Path, output_root: Path) -> dict[str, Any]:
    raw_fields, raw_rows = read_tsv(raw_path)
    _, selected_rows = read_tsv(selected_path)
    required = {
        "raw_candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
        "target_patch_id", "design_mode", "cdr3_length",
    }
    if not required <= set(raw_fields):
        raise RuntimeError(f"raw_fields_missing:{sorted(required - set(raw_fields))}")
    selected_hashes = {row["sequence_sha256"] for row in selected_rows}
    representatives: dict[str, dict[str, str]] = {}
    duplicate_unselected_hashes = 0
    excluded_c0371 = 0
    excluded_selected = 0
    for source in sorted(raw_rows, key=lambda row: row["raw_candidate_id"]):
        if source["parent_framework_cluster"] == "C0371":
            excluded_c0371 += 1
            continue
        if source["sequence_sha256"] in selected_hashes:
            excluded_selected += 1
            continue
        if source["sequence_sha256"] in representatives:
            duplicate_unselected_hashes += 1
            continue
        representatives[source["sequence_sha256"]] = dict(source)

    rows = list(representatives.values())
    tier_order = {"P1_EXPLOIT": 0, "P2_PARENT": 1, "P3_LONG_CDR3": 2, "P4_DIVERSITY": 3}
    for row in rows:
        row["candidate_id"] = row["raw_candidate_id"].replace("RAWV4H__", "V4I_LATENT__", 1)
        row["research_pool_state"] = "LATENT_UNSEEN_PENDING_FULL_QC"
        row["priority_high_yield_parent"] = str(row["parent_framework_cluster"] in HIGH_YIELD_PARENTS).lower()
        row["priority_cdr3_19_20"] = str(int(row["cdr3_length"]) >= 19).lower()
        row["priority_tier"] = priority_tier(row)
    rows.sort(
        key=lambda row: (
            tier_order[row["priority_tier"]],
            -int(row["cdr3_length"]),
            row["parent_framework_cluster"],
            row["target_patch_id"],
            0 if row["design_mode"] == "H3" else 1,
            row["candidate_id"],
        )
    )
    for index, row in enumerate(rows, 1):
        row["priority_rank"] = str(index)

    if len(rows) != 970:
        raise RuntimeError(f"latent_pool_expected_970:{len(rows)}")
    if len({row["candidate_id"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate_candidate_id")
    if len({row["sequence_sha256"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate_sequence_hash")
    for row in rows:
        observed = hashlib.sha256(row["sequence"].encode()).hexdigest()
        if observed != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_hash_mismatch:{row['candidate_id']}")

    output_root.mkdir(parents=True, exist_ok=False)
    outputs = output_root / "outputs"
    outputs.mkdir()
    fields = list(rows[0])
    manifest = outputs / "latent970_candidates.tsv"
    fasta = outputs / "latent970_candidates.fasta"
    write_tsv(manifest, rows, fields)
    atomic_text(fasta, "".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in rows))

    counts = lambda key: dict(sorted(collections.Counter(row[key] for row in rows).items()))
    audit = {
        "schema_version": "pvrig_v4_i_latent_pool_v1",
        "status": "PASS_LATENT970_EXACT_UNIQUE_POOL",
        "input_raw_rows": len(raw_rows),
        "selected_hash_exclusions": len(selected_hashes),
        "excluded_selected_rows": excluded_selected,
        "excluded_c0371_rows": excluded_c0371,
        "duplicate_unselected_hashes_collapsed": duplicate_unselected_hashes,
        "candidate_count": len(rows),
        "unique_sequence_count": len(rows),
        "priority_tier_counts": counts("priority_tier"),
        "parent_counts": counts("parent_framework_cluster"),
        "patch_counts": counts("target_patch_id"),
        "design_mode_counts": counts("design_mode"),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path = output_root / "audit.json"
    atomic_text(audit_path, json.dumps(audit, indent=2, sort_keys=True) + "\n")
    receipt = {
        "schema_version": "pvrig_v4_i_latent_pool_receipt_v1",
        "status": "PASS_HASH_CLOSED_LATENT970_POOL",
        "candidate_count": len(rows),
        "input_hashes": {"raw": sha256(raw_path), "selected": sha256(selected_path)},
        "output_hashes": {
            "outputs/latent970_candidates.tsv": sha256(manifest),
            "outputs/latent970_candidates.fasta": sha256(fasta),
            "audit.json": sha256(audit_path),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_text(output_root / "receipt.json", json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.raw, args.selected, args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
