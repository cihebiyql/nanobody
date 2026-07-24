#!/usr/bin/env python3
"""Prepare and finalize the first expanded 448-candidate numbering audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path("/mnt/d/work/抗体")
SOURCE = (
    ROOT
    / "node1/reports/pvrig_finalist_screening_standard_v1_20260724/dry_run/"
    "core448_candidates.tsv"
)
OUT = (
    ROOT
    / "node1/reports/pvrig_positive_first_screen_calibration_v1_20260724/"
    "expansion/core448"
)
FASTA = OUT / "core448.fasta"
ANARCI = OUT / "core448_anarci_H.csv"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(SOURCE, sep="\t")
    if len(frame) != 448:
        raise ValueError(f"expected 448 rows, observed {len(frame)}")
    if frame["candidate_id"].duplicated().any():
        raise ValueError("duplicate candidate IDs")
    if frame["sequence"].duplicated().any():
        raise ValueError("duplicate exact sequences")

    standard = set("ACDEFGHIKLMNPQRSTVWY")
    frame["recomputed_sequence_sha256"] = frame["sequence"].map(
        lambda seq: hashlib.sha256(seq.encode()).hexdigest()
    )
    frame["sequence_hash_match"] = (
        frame["recomputed_sequence_sha256"] == frame["sequence_sha256"]
    )
    frame["standard_20aa"] = frame["sequence"].map(lambda seq: set(seq) <= standard)
    frame["audit_batch"] = [f"B{index // 64 + 1:03d}" for index in range(len(frame))]
    frame["audit_batch_row"] = [index % 64 + 1 for index in range(len(frame))]

    if not frame["sequence_hash_match"].all():
        raise ValueError("sequence hash mismatch detected")
    if not frame["standard_20aa"].all():
        raise ValueError("non-standard amino acid detected")

    frame.to_csv(OUT / "core448_pre_numbering_manifest.tsv", sep="\t", index=False)
    with FASTA.open("w", encoding="utf-8") as handle:
        for row in frame.itertuples(index=False):
            handle.write(f">{row.candidate_id}\n{row.sequence}\n")

    receipt = {
        "stage": "PREPARED",
        "source": str(SOURCE),
        "source_sha256": sha256(SOURCE),
        "rows": len(frame),
        "unique_candidate_ids": int(frame["candidate_id"].nunique()),
        "unique_sequences": int(frame["sequence"].nunique()),
        "sequence_hash_match": int(frame["sequence_hash_match"].sum()),
        "standard_20aa": int(frame["standard_20aa"].sum()),
        "audit_batches": frame["audit_batch"].nunique(),
        "batch_sizes": {
            key: int(value) for key, value in frame["audit_batch"].value_counts().sort_index().items()
        },
        "fasta": str(FASTA),
        "fasta_sha256": sha256(FASTA),
    }
    write_json(OUT / "PREPARE_RECEIPT.json", receipt)
    return receipt


def cdr_from_anarci(row: pd.Series, start: int, end: int) -> str:
    residues: list[str] = []
    for column in row.index:
        text = str(column)
        prefix = ""
        for char in text:
            if char.isdigit():
                prefix += char
            else:
                break
        if not prefix:
            continue
        position = int(prefix)
        if start <= position <= end:
            value = row[column]
            if pd.notna(value) and str(value) not in {"-", ""}:
                residues.append(str(value))
    return "".join(residues)


def finalize() -> dict:
    if not ANARCI.exists():
        raise FileNotFoundError(f"ANARCI output missing: {ANARCI}")
    manifest = pd.read_csv(OUT / "core448_pre_numbering_manifest.tsv", sep="\t")
    numbered = pd.read_csv(ANARCI)
    numbered = numbered.rename(columns={"Id": "candidate_id"})
    if numbered["candidate_id"].duplicated().any():
        raise ValueError("duplicate ANARCI candidate IDs")

    numbered["fresh_cdr1"] = numbered.apply(lambda row: cdr_from_anarci(row, 27, 38), axis=1)
    numbered["fresh_cdr2"] = numbered.apply(lambda row: cdr_from_anarci(row, 56, 65), axis=1)
    numbered["fresh_cdr3"] = numbered.apply(lambda row: cdr_from_anarci(row, 105, 117), axis=1)
    audit = manifest.merge(
        numbered[
            [
                "candidate_id",
                "chain_type",
                "score",
                "seqstart_index",
                "seqend_index",
                "fresh_cdr1",
                "fresh_cdr2",
                "fresh_cdr3",
            ]
        ],
        on="candidate_id",
        how="left",
        validate="one_to_one",
    )
    audit["anarci_row_present"] = audit["chain_type"].notna()
    audit["heavy_chain"] = audit["chain_type"].eq("H")
    audit["cdr1_match"] = audit["cdr1"] == audit["fresh_cdr1"]
    audit["cdr2_match"] = audit["cdr2"] == audit["fresh_cdr2"]
    audit["cdr3_match"] = audit["cdr3"] == audit["fresh_cdr3"]
    audit["all_cdr_match"] = audit[["cdr1_match", "cdr2_match", "cdr3_match"]].all(axis=1)
    audit["numbering_disposition"] = audit["all_cdr_match"].map(
        {True: "PASS", False: "REVIEW_ANARCI_CDR_BOUNDARY"}
    )
    audit.to_csv(OUT / "core448_numbering_audit.tsv", sep="\t", index=False)
    audit[audit["all_cdr_match"]].to_csv(
        OUT / "core437_numbering_pass.tsv", sep="\t", index=False
    )
    audit[~audit["all_cdr_match"]].to_csv(
        OUT / "core11_numbering_review.tsv", sep="\t", index=False
    )

    all_numbered = (
        len(audit) == 448
        and audit["anarci_row_present"].all()
        and audit["heavy_chain"].all()
        and audit["cdr1_match"].all()
        and audit["cdr3_match"].all()
    )
    all_cdr_match = audit["all_cdr_match"].all()
    receipt = {
        "stage": "FRESH_ANARCI_COMPLETE",
        "rows": len(audit),
        "anarci_rows": len(numbered),
        "anarci_row_present": int(audit["anarci_row_present"].sum()),
        "heavy_chain_rows": int(audit["heavy_chain"].sum()),
        "cdr1_matches": int(audit["cdr1_match"].sum()),
        "cdr2_matches": int(audit["cdr2_match"].sum()),
        "cdr3_matches": int(audit["cdr3_match"].sum()),
        "all_cdr_matches": int(audit["all_cdr_match"].sum()),
        "numbering_review_rows": int((~audit["all_cdr_match"]).sum()),
        "status": "PASS" if all_numbered and all_cdr_match else (
            "PASS_WITH_CDR_BOUNDARY_REVIEW" if all_numbered else "FAIL"
        ),
        "anarci_sha256": sha256(ANARCI),
        "audit_sha256": sha256(OUT / "core448_numbering_audit.tsv"),
        "next_action": (
            "Run official ab-data-validator and complete public/local positive CDR library "
            "novelty audit in a new output directory. Quarantine rows in "
            "core11_numbering_review.tsv until official CDR extraction and identity are recomputed."
        ),
    }
    write_json(OUT / "NUMBERING_RECEIPT.json", receipt)

    files = [
        "core448.fasta",
        "core448_pre_numbering_manifest.tsv",
        "PREPARE_RECEIPT.json",
        "core448_anarci_H.csv",
        "anarci.stdout.log",
        "anarci.stderr.log",
        "core448_numbering_audit.tsv",
        "core437_numbering_pass.tsv",
        "core11_numbering_review.tsv",
        "NUMBERING_RECEIPT.json",
    ]
    (OUT / "SHA256SUMS").write_text(
        "\n".join(f"{sha256(OUT / file)}  {file}" for file in files) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    value = finalize() if args.finalize else prepare()
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
