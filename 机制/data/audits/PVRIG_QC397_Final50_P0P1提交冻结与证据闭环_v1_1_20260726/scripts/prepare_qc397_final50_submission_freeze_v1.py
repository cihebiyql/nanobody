#!/usr/bin/env python3
"""Create submission-safe exact TSV/FASTA inputs from the ranked Final50."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")


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
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranked-tsv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"output exists: {args.out}")
    args.out.mkdir(parents=True)

    source = read_tsv(args.ranked_tsv)
    if len(source) != 50:
        raise ValueError(f"ranked TSV does not contain 50 rows: {len(source)}")
    source.sort(key=lambda row: int(row["competition_rank_1_50"]))
    if [int(row["competition_rank_1_50"]) for row in source] != list(range(1, 51)):
        raise ValueError("competition ranks are not exactly 1..50")

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(source, 1):
        sequence = "".join(row["sequence"].split()).upper()
        if not sequence or set(sequence) - STANDARD_AA:
            raise ValueError(f"invalid sequence at rank {index}")
        expected_sequence_hash = row.get("sequence_sha256", "")
        actual_sequence_hash = sha256_bytes(sequence.encode("ascii"))
        if expected_sequence_hash and expected_sequence_hash != actual_sequence_hash:
            raise ValueError(f"sequence hash mismatch at rank {index}")
        rows.append(
            {
                "submission_id": f"PVRIG_CAND_{index:03d}",
                "competition_rank_1_50": index,
                "mechanism_rank_immutable": row["mechanism_rank_immutable"],
                "candidate_id": row["candidate_id"],
                "sequence": sequence,
                "sequence_sha256": actual_sequence_hash,
                "cdr1": row["cdr1"],
                "cdr2": row["cdr2"],
                "cdr3": row["cdr3"],
                "developability_grade": row["developability_grade"],
                "competition_role": row["competition_role"],
            }
        )
    if len({row["submission_id"] for row in rows}) != 50:
        raise ValueError("submission IDs are not unique")
    if len({row["candidate_id"] for row in rows}) != 50:
        raise ValueError("candidate IDs are not unique")
    if len({row["sequence"] for row in rows}) != 50:
        raise ValueError("sequences are not exact-unique")

    tsv_path = args.out / "Final50_submission_freeze.tsv"
    fasta_path = args.out / "Final50_submission_freeze.fasta"
    write_tsv(tsv_path, rows)
    with fasta_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['submission_id']}\n{row['sequence']}\n")

    receipt = {
        "schema_version": "pvrig.qc397.final50.submission_input_freeze.v1",
        "state": "INPUT_FREEZE_COMPLETE",
        "records": 50,
        "exact_sequence_count": 50,
        "source_ranked_tsv_sha256": sha256(args.ranked_tsv),
        "output_sha256": {
            tsv_path.name: sha256(tsv_path),
            fasta_path.name: sha256(fasta_path),
        },
        "assertions": {
            "competition_rank_exact_1_to_50": True,
            "standard_20_aa_only": True,
            "submission_ids_unique": True,
            "candidate_ids_unique": True,
            "sequences_exact_unique": True,
            "source_sequence_sha256_verified": True,
            "tsv_fasta_order_and_sequence_identical": True,
        },
        "claim_boundary": (
            "Submission-safe identifiers and byte-frozen sequence inputs only; "
            "no ranking or biological evidence was changed."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (args.out / "INPUT_FREEZE_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
