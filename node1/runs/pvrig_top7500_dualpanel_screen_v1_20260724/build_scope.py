#!/usr/bin/env python3
"""Freeze the old-priority and C2-refined Top7500 candidate universe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


EXPECTED_PANEL_ROWS = 7_500
EXPECTED_OVERLAP = 1_280
EXPECTED_UNION = 13_720


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_panel(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    required = {"candidate_id", "sequence", "sequence_sha256"}
    missing = sorted(required - set(fields))
    if missing:
        raise ValueError(f"{path}: missing fields {missing}")
    if len(rows) != EXPECTED_PANEL_ROWS:
        raise ValueError(f"{path}: expected {EXPECTED_PANEL_ROWS} rows, got {len(rows)}")
    seen_ids: set[str] = set()
    seen_sequences: set[str] = set()
    for row in rows:
        candidate_id = row["candidate_id"].strip()
        sequence = row["sequence"].strip().upper()
        expected_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if row["sequence_sha256"].strip() != expected_hash:
            raise ValueError(f"{path}: sequence hash mismatch for {candidate_id}")
        if candidate_id in seen_ids:
            raise ValueError(f"{path}: duplicate candidate_id {candidate_id}")
        if sequence in seen_sequences:
            raise ValueError(f"{path}: duplicate exact sequence for {candidate_id}")
        seen_ids.add(candidate_id)
        seen_sequences.add(sequence)
        row["candidate_id"] = candidate_id
        row["sequence"] = sequence
        row["sequence_sha256"] = expected_hash
    return rows, fields


def write_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--c2", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    old_rows, _ = read_panel(args.old)
    c2_rows, _ = read_panel(args.c2)
    old_by_id = {row["candidate_id"]: row for row in old_rows}
    c2_by_id = {row["candidate_id"]: row for row in c2_rows}
    overlap_ids = set(old_by_id) & set(c2_by_id)
    if len(overlap_ids) != EXPECTED_OVERLAP:
        raise ValueError(
            f"expected {EXPECTED_OVERLAP} candidate_id overlap, got {len(overlap_ids)}"
        )
    for candidate_id in sorted(overlap_ids):
        if (
            old_by_id[candidate_id]["sequence_sha256"]
            != c2_by_id[candidate_id]["sequence_sha256"]
        ):
            raise ValueError(f"overlap sequence mismatch for {candidate_id}")

    union_ids = set(old_by_id) | set(c2_by_id)
    if len(union_ids) != EXPECTED_UNION:
        raise ValueError(f"expected {EXPECTED_UNION} union rows, got {len(union_ids)}")

    args.out.mkdir(parents=True, exist_ok=True)
    old_order = {row["candidate_id"]: index + 1 for index, row in enumerate(old_rows)}
    c2_order = {row["candidate_id"]: index + 1 for index, row in enumerate(c2_rows)}
    membership: list[dict[str, str]] = []
    union_rows: list[dict[str, str]] = []
    for candidate_id in sorted(
        union_ids,
        key=lambda value: (
            c2_order.get(value, 10**9),
            old_order.get(value, 10**9),
            value,
        ),
    ):
        source = c2_by_id.get(candidate_id) or old_by_id[candidate_id]
        in_old = candidate_id in old_by_id
        in_c2 = candidate_id in c2_by_id
        membership.append(
            {
                "candidate_id": candidate_id,
                "sequence": source["sequence"],
                "sequence_sha256": source["sequence_sha256"],
                "panel_membership": (
                    "OLD_AND_C2" if in_old and in_c2 else "OLD_ONLY" if in_old else "C2_ONLY"
                ),
                "old_priority_rank": str(old_order.get(candidate_id, "")),
                "c2_refined_rank": str(c2_order.get(candidate_id, "")),
                "parent_framework_cluster": source.get("parent_framework_cluster", ""),
                "design_method": source.get("design_method", ""),
                "tnp_review_tier": source.get("tnp_review_tier", ""),
            }
        )
        union_rows.append(source)

    old_fasta = args.out / "OLD_PRIORITY_TOP7500.fasta"
    c2_fasta = args.out / "C2_REFINED_TOP7500.fasta"
    union_fasta = args.out / "TOP7500_UNION_13720.fasta"
    membership_tsv = args.out / "TOP7500_UNION_13720_MEMBERSHIP.tsv"
    write_fasta(old_fasta, old_rows)
    write_fasta(c2_fasta, c2_rows)
    write_fasta(union_fasta, union_rows)
    write_tsv(
        membership_tsv,
        membership,
        [
            "candidate_id",
            "sequence",
            "sequence_sha256",
            "panel_membership",
            "old_priority_rank",
            "c2_refined_rank",
            "parent_framework_cluster",
            "design_method",
            "tnp_review_tier",
        ],
    )

    outputs = [old_fasta, c2_fasta, union_fasta, membership_tsv]
    receipt = {
        "schema_version": "pvrig.top7500.dualpanel.scope.v1",
        "status": "PASS_FROZEN_TWO_TOP7500_UNION",
        "claim_boundary": (
            "Candidate identity, sequence and panel-membership freeze only; "
            "no binding, affinity or experimental blocking claim."
        ),
        "counts": {
            "old_priority": len(old_rows),
            "c2_refined": len(c2_rows),
            "overlap": len(overlap_ids),
            "old_only": len(set(old_by_id) - set(c2_by_id)),
            "c2_only": len(set(c2_by_id) - set(old_by_id)),
            "union": len(union_ids),
        },
        "inputs": {
            "old_priority": {"path": str(args.old), "sha256": sha256_file(args.old)},
            "c2_refined": {"path": str(args.c2), "sha256": sha256_file(args.c2)},
        },
        "outputs": {
            path.name: {"sha256": sha256_file(path)} for path in outputs
        },
    }
    receipt_path = args.out / "SCOPE_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums = outputs + [receipt_path]
    (args.out / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksums),
        encoding="ascii",
    )
    print(json.dumps(receipt["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
