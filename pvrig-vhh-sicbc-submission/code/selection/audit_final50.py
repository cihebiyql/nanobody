#!/usr/bin/env python3
"""Perform the final submission compliance, diversity, provenance and hash audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-root", type=Path, required=True)
    parser.add_argument("--final-qc", type=Path, required=True)
    parser.add_argument("--top80-receipt", type=Path, required=True)
    parser.add_argument("--md-receipt", type=Path, required=True)
    args = parser.parse_args()
    root = args.final_root
    final_path = root / "final50_ranked.tsv"
    final_fasta = root / "final50_ranked.fasta"
    top10_path = root / "top10_priority.tsv"
    top10_fasta = root / "top10_priority.fasta"
    preaudit_path = root / "FINAL50_PREAUDIT.json"
    required = [
        final_path, final_fasta, top10_path, top10_fasta, preaudit_path,
        args.final_qc, args.top80_receipt, args.md_receipt,
    ]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        raise ValueError("final audit inputs are missing or empty")
    final = read_tsv(final_path)
    top10 = read_tsv(top10_path)
    qc = read_tsv(args.final_qc)
    if len(final) != 50 or len(top10) != 10 or len(qc) != 50:
        raise ValueError("final50/top10/final-QC row counts are not 50/10/50")
    final_by_id = {row["candidate_id"]: row for row in final}
    qc_by_id = {row["candidate_id"]: row for row in qc}
    if len(final_by_id) != 50 or set(final_by_id) != set(qc_by_id):
        raise ValueError("final candidate ID uniqueness/QC set closure failed")
    if not {row["candidate_id"] for row in top10}.issubset(final_by_id):
        raise ValueError("Top10 is not a subset of final50")
    sequences = [row["sequence"] for row in final]
    cdr3s = [row["cdr3"] for row in final]
    parent_counts = Counter(row["parent_cluster"] for row in final)
    route_counts = Counter(row["route"] for row in final)
    cluster_counts = Counter(row["cdr3_diversity_cluster"] for row in final)

    def direct_cdr3_identity(left: str, right: str) -> float:
        if not left or len(left) != len(right):
            return 0.0
        return sum(a == b for a, b in zip(left, right)) / len(left)

    max_pairwise_cdr3_identity = max(
        (
            direct_cdr3_identity(left, right)
            for index, left in enumerate(cdr3s)
            for right in cdr3s[index + 1 :]
        ),
        default=0.0,
    )
    checks = {
        "exact_sequence_duplicates_zero": len(set(sequences)) == 50,
        "exact_cdr3_duplicates_zero": len(set(cdr3s)) == 50,
        "direct_pairwise_cdr3_identity_below_0p80": (
            max_pairwise_cdr3_identity < 0.80
        ),
        "parent_max_fifteen": max(parent_counts.values(), default=0) <= 15,
        "route_max_thirtyfive": max(route_counts.values(), default=0) <= 35,
        "minimum_four_parents": len(parent_counts) >= 4,
    }
    audit_rows: list[dict[str, Any]] = []
    for candidate_id in final_by_id:
        row = final_by_id[candidate_id]
        qc_row = qc_by_id[candidate_id]
        observed_sequence = qc_row.get("sequence", row["sequence"])
        row_checks = {
            "sequence_match": observed_sequence == row["sequence"],
            "official_validator_pass": qc_row.get("official_validator_pass") == "PASS",
            "similarity_filter_pass": qc_row.get("pass_similarity_filter") == "PASS",
            "no_qc_hard_fail": qc_row.get("hard_fail", "").strip().lower() == "false",
        }
        audit_rows.append(
            {
                "candidate_id": candidate_id,
                **{key: str(value).lower() for key, value in row_checks.items()},
                "qc_reason_summary": qc_row.get("reason_summary", ""),
                "sequence_sha256": hashlib.sha256(
                    row["sequence"].encode("ascii")
                ).hexdigest(),
            }
        )
        if not all(row_checks.values()):
            raise ValueError(f"final QC failed for {candidate_id}: {row_checks}")
    if not all(checks.values()):
        raise ValueError(f"final diversity checks failed: {checks}")
    audit_path = root / "final50_validation_audit.tsv"
    write_tsv(audit_path, audit_rows)
    receipt = {
        "schema_version": "pvrig.final50.audited.v1",
        "state": "FINAL50_COMPLETE",
        "count": 50,
        "top10_count": 10,
        "official_validator_pass": 50,
        "similarity_filter_pass": 50,
        "hard_fail_count": 0,
        "diversity_checks": checks,
        "parent_counts": dict(parent_counts),
        "route_counts": dict(route_counts),
        "cdr3_cluster_max": max(cluster_counts.values(), default=0),
        "single_linkage_cdr3_clusters_reporting_only": True,
        "max_direct_pairwise_cdr3_identity": max_pairwise_cdr3_identity,
        "md_role": "DESCRIPTIVE_ONLY",
        "input_hashes": {str(path): sha256_file(path) for path in required},
        "output_hashes": {
            final_path.name: sha256_file(final_path),
            final_fasta.name: sha256_file(final_fasta),
            top10_path.name: sha256_file(top10_path),
            top10_fasta.name: sha256_file(top10_fasta),
            audit_path.name: sha256_file(audit_path),
        },
        "claim_boundary": (
            "Audited computational submission portfolio; experimental BLI, Kd, "
            "IC50, expression and purity remain to be measured by the organizer."
        ),
    }
    receipt_path = root / "FINAL50_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = [final_path, final_fasta, top10_path, top10_fasta, audit_path, receipt_path]
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in outputs),
        encoding="ascii",
    )
    print(json.dumps({"final50": 50, "top10": 10, "validator_pass": 50}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
